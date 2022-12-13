import os
import re
import random
import selfies as sf
from tqdm import tqdm
from rdkit import Chem
from rdkit import RDLogger
RDLogger.DisableLog('rdApp.*')
from SmilesPE.tokenizer import SPE_Tokenizer


TASKS = ['product-pred', 'reactant-pred', 'reagent-pred',
         'reactant-pred-single', 'reactant-pred-noreag']
FOLDS = [1, 2, 5, 10, 20]
SPLITS = ['test', 'val', 'train']
ORIGINAL_DIR = os.path.join('data', 'original')
SPE_ENCODER_PATH_SMILES = os.path.join(ORIGINAL_DIR, 'spe_codes_smiles.txt')
SPE_ENCODER_PATH_SELFIES = os.path.join(ORIGINAL_DIR, 'spe_codes_selfies.txt')


def main():
    random.seed(1234)  # this is enough for replicable augmentation
    create_smiles_datasets()  # original data -> all tasks & data augmentations
    create_selfies_datasets()  # smiles data -> selfies data
    create_spe_datasets()  # smiles and selfies atom data -> spe data


def create_smiles_datasets():
    print('\nStarted generating smiles datasets')
    for task in TASKS:
        print('-- Task: %s' % task)
        for fold in FOLDS:
            print('---- Fold: %s' % fold)
            generate_augmented_dataset(task, fold)


def create_selfies_datasets():
    print('\nStarted generating selfies datasets from smiles datasets')
    for folder, _, files in os.walk('data'):
        if 'smiles' in folder and 'x1-' in folder\
            and '-single' not in folder and '-noreag' not in folder:
            for smiles_file in [f for f in files if '.txt' in f]:
                smiles_full_path = os.path.join(folder, smiles_file)
                write_selfies_file_from_smiles_file(smiles_full_path)


def create_spe_datasets():
    print('\nStarted generating spe datasets from atom-tokenized datasets')
    for folder, _, files in os.walk('data'):
        if 'atom' in folder and 'x1-' in folder\
            and '-single' not in folder and '-noreag' not in folder:
            for atom_file in [f for f in files if '.txt' in f]:
                atom_full_path = os.path.join(folder, atom_file)
                write_spe_file_from_atom_file(atom_full_path)


def write_selfies_file_from_smiles_file(smiles_path):
    selfies_path = smiles_path.replace('smiles', 'selfies')
    os.makedirs(os.path.split(selfies_path)[0], exist_ok=True)
    with open(smiles_path, 'r') as f_smiles,\
         open(selfies_path, 'w') as f_selfies:
        progress_bar = tqdm(f_smiles.readlines())
        for smiles in progress_bar:
            progress_bar.set_description('Convert %s to selfies' % smiles_path)
            f_selfies.write(create_selfies_from_smiles(smiles) + '\n')
        

def write_spe_file_from_atom_file(atom_path):
    # Find the correct spe-tokenizer (smiles or selfies)
    if 'smiles' in atom_path:
        spe_path = SPE_ENCODER_PATH_SMILES
    elif 'selfies' in atom_path:
        spe_path = SPE_ENCODER_PATH_SELFIES
    else:
        raise ValueError('There is something wrong with the input data path')
    with open(spe_path, 'r') as spe_file:
        tokenizer = SPE_Tokenizer(codes=spe_file)

    # Build a directory and a path for the new spe-tokenized dataset
    spe_path = atom_path.replace('atom', 'spe')
    os.makedirs(os.path.split(spe_path)[0], exist_ok=True)

    # Build spe-tokenized dataset from the original dataset
    with open(atom_path, 'r') as in_file,\
         open(spe_path, 'w') as out_file:
        progress_bar = tqdm(in_file.readlines())
        for atom_tokenized_rxn in progress_bar:
            progress_bar.set_description('Convert %s to spe' % atom_path)
            rxn = atom_tokenized_rxn.replace(' ', '')
            spe_tokenized_rnx = tokenizer.tokenize(rxn)
            out_file.write(spe_tokenized_rnx + '\n')


def generate_augmented_dataset(task, fold):
    out_subdir = 'x%s-reag%s' % (fold)
    out_fulldir = os.path.join('data', task, 'smiles', 'atom', out_subdir)
    os.makedirs(out_fulldir, exist_ok=True)
    for split in SPLITS:
        write_smiles_files(out_fulldir, task, fold, split)


def write_smiles_files(out_dir, task, fold, split):
    with open(os.path.join(ORIGINAL_DIR, 'src-%s.txt' % split), 'r') as src_in,\
         open(os.path.join(ORIGINAL_DIR, 'tgt-%s.txt' % split), 'r') as tgt_in,\
         open(os.path.join(out_dir, 'src-%s.txt' % split), 'w') as src_out,\
         open(os.path.join(out_dir, 'tgt-%s.txt' % split), 'w') as tgt_out:

        noreag_flag = '-noreag' in task
        progress_bar = tqdm(zip(src_in.readlines(), tgt_in.readlines()))
        for src, tgt in progress_bar:
            progress_bar.set_description('------ Split %s' % split)
            species = parse_rxn(src, tgt, noreag_flag)
            new_src, new_tgt = create_new_sample(task, **species)
            if len(new_src) == 0 or len(new_tgt) == 0: continue
            new_src, new_tgt = augment_sample(new_src, new_tgt, fold)
            src_out.write(new_src + '\n')
            tgt_out.write(new_tgt + '\n')


def parse_rxn(src, tgt, noreag_flag):
    src, tgt = src.strip(), tgt.strip()
    if '  >' in src: src = src.replace('  >', ' > ')
    precursors = src.split(' > ')

    reactants, reagents = [p.split(' . ') for p in precursors]
    if noreag_flag: reagents = []
    products = tgt.split(' . ')  # should we pick only the largest?

    return {'reactants': [r for r in reactants if r != ''],\
            'reagents': [r for r in reagents if r != ''],\
            'products': [p for p in products if p != '']}


def create_new_sample(task, reactants, reagents, products):
    if task == 'product-pred':
        new_src = ' . '.join(reactants + reagents)
        new_tgt = ' . '.join(products)
    elif task in ['reactant-pred', 'reactant-pred-noreag']:
        new_src = ' . '.join(reagents + products)
        new_tgt = ' . '.join(reactants)
    elif task == 'reagent-pred':
        new_src = ' . '.join(reactants + products)
        new_tgt = ' . '.join(reagents)
    elif task == 'reactant-pred-single':
        single_react = random.sample(reactants, 1)  # list
        other_reacts = [r for r in reactants if r != single_react]
        new_src = ' . '.join(other_reacts + reagents + products)
        new_tgt = ' . '.join(single_react)
    else:
        raise ValueError('Bad task name')
    return new_src, new_tgt


def augment_sample(src, tgt, fold):
    if fold == 1: return src, tgt  # i.e., no augmentation
    src_smiles_list = src.split(' . ')
    src_augm = [generate_n_equivalent_smiles(s, fold) for s in src_smiles_list]
    src_augm = [list(s) for s in list(zip(*src_augm))]  # re-group molecules
    [random.shuffle(s) for s in src_augm]  # shuffle molecule order
    src_augm = [' . '.join(s) for s in src_augm]  # put back in token string
    tgt_augm = [' . '.join(sorted(tgt.split(' . ')))] * fold  # de-augmentation
    return '\n'.join(src_augm), '\n'.join(tgt_augm)


def generate_n_equivalent_smiles(smiles_tokens, n):
    smiles = smiles_tokens.replace(' ', '')
    mol = Chem.MolFromSmiles(smiles)
    new_smiles_list = [smiles]
    trials = 0

    while len(new_smiles_list) < n and trials < 2 * n:
        new_smiles = Chem.MolToSmiles(mol, doRandom=True, canonical=False)
        trials += 1
        if new_smiles not in new_smiles_list:
            new_smiles_list.append(new_smiles)

    if len(new_smiles_list) < n:  # complete list for very short molecules
        factor = n // len(new_smiles_list) + 1
        new_smiles_list = (new_smiles_list * factor)[:n]

    new_smiles_list = [atomwise_tokenizer(s) for s in new_smiles_list]
    return new_smiles_list


def atomwise_tokenizer(smiles):
    # From https://github.com/pschwllr/MolecularTransformer
    # Should also work with selfies (thanks to the [])
    pattern = '(\[[^\]]+]|Br?|Cl?|N|O|S|P|F|I|b|c|n|o|s|p|\(|\)'+\
              '|\.|=|#|-|\+|\\\\|\/|:|~|@|\?|>|\*|\$|\%[0-9]{2}|[0-9])'
    regex = re.compile(pattern)
    tokens = [token for token in regex.findall(smiles)]
    assert smiles == ''.join(tokens)
    return ' '.join(tokens)
    

def canonicalize_smiles(smiles):
    try:
        return Chem.MolToSmiles(Chem.MolFromSmiles(smiles))
    except:  # Boost.Python.ArgumentError
        return smiles


def create_selfies_from_smiles(smiles):
    smiles = canonicalize_smiles(smiles.replace(' ', ''))  # needed?
    try:
        selfies = sf.encoder(smiles)
    except sf.EncoderError:
        selfies = create_selfies_from_smiles_molecule_by_molecule(smiles)
    return atomwise_tokenizer(selfies)


def create_selfies_from_smiles_molecule_by_molecule(smiles):
    smiles_molecules = smiles.split('.')
    selfies_molecules = []
    for smiles_molecule in smiles_molecules:
        try:
            selfies_molecules.append(sf.encoder(smiles_molecule))
        except sf.EncoderError:
            # Molecules that didn't work in the USPTO-MIT dataset:
            # O=I(=O)Cl
            # Cl[IH2](Cl)Cl
            # O=[IH2]c1ccccc1
            # F[P-](F)(F)(F)(F)F
            # O=C(O)c1ccccc1I(=O)=O
            # O=C1OI(=O)(O)c2ccccc21
            # S=[Re](=S)(=S)(=S)(=S)(=S)=S
            # CC1(C)O[IH2](C(F)(F)F)c2ccccc21
            # C12C3C4C5C1[Fe]23451678C2C1C6C7C28
            # C12C3C4C5C1[Zr]23451678C2C1C6C7C28
            # O=C(OI(OC(=O)C(F)(F)F)c1ccccc1)C(F)(F)F
            # CC(=O)OI1(OC(C)=O)(OC(C)=O)OC(=O)c2ccccc21
            # Cc1ccc(S(=O)(=O)N=C2CCCC[IH2]2c2ccccc2)cc1
            # O=C(O[IH2](OC(=O)C(F)(F)F)c1ccccc1)C(F)(F)F
            # COc1cc2c(cc1OC)C([PH2](c1ccccc1)(c1ccccc1)c1ccccc1)OC2=O
            # O=c1[nH]c2c3occc3c(F)c(F)c2n1-c1ccc([IH]S(=O)(=O)C2CC2COCc2ccccc2)cc1F
            # print('This molecule didn''t work %s' % smiles_molecule)
            selfies_molecules.append('?') # to preserve # molecules / rxn
    return '.'.join(selfies_molecules)


if __name__ == '__main__':
    main()