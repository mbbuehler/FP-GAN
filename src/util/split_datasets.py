import os
import re
from os import symlink
import numpy as np


BASE_DATA_DIR = os.getenv('FPGAN_BASE_DATA_DIR', '/disks/data4/marcel/FP-GAN/data')


class DatasetSplitFactory:
    def __init__(self,
                 path_source,
                 path_train,
                 path_validation,
                 path_test,
                 id_pattern):
        self.path_source = path_source
        self.path_train = path_train
        self.path_validation = path_validation
        self.path_test = path_test
        self.id_pattern = id_pattern

    @staticmethod
    def create_filepath(folder, id, suffix):
        filename = "{}.{}".format(id, suffix)
        return os.path.join(folder, filename)

    @staticmethod
    def create_folder_if_not_exists(path):
        if not os.path.exists(path):
            os.mkdir(path)

    def copy_samples(self, ids, path_from, path_to):
        # from shutil import rmtree
        # rmtree(path_to)

        self.create_folder_if_not_exists(path_to)
        print("Copying {} images from {} to {}".format(len(ids), path_from, path_to))
        for id in ids:
            file_jpg_in = self.create_filepath(path_from, id, 'jpg')
            file_json_in = self.create_filepath(path_from, id, 'json')

            file_jpg_out = self.create_filepath(path_to, id, 'jpg')
            file_json_out = self.create_filepath(path_to, id, 'json')

            if os.path.isfile(file_jpg_out) or os.path.isfile(file_json_out):
                os.unlink(file_jpg_out)
                os.unlink(file_json_out)

            symlink(file_jpg_in, file_jpg_out)
            symlink(file_json_in, file_json_out)
        print("Copied {} images".format(len(ids)))

    def create_and_save(self, all_ids, size, from_path, to_path):
        print("Generating {} samples...".format(size))
        samples = np.random.choice(list(set(all_ids)), size=size,
                                   replace=False)
        self.copy_samples(samples, from_path, to_path)
        return samples

    def read_ids(self, path):
        files = os.listdir(path)
        ids = []
        for f in files:
            match = re.findall(self.id_pattern, f)
            if match:
                ids.append(match[0])
        # n_duplicates = len(ids) - len(set(ids))
        ids = list(set(ids))
        print("Processing {} ids".format(len(ids)))
        return ids

    def run(self):
        raise NotImplementedError("Use a subclass!")


class StandardDatasetSplitFactory(DatasetSplitFactory):
    def __init__(self, test_size=10000,
                 validation_size=10000, **kwargs):
        super().__init__(**kwargs)
        self.test_size = test_size
        self.validation_size = validation_size

    def run(self):
        # Get all ids from the source folder (without suffix or _clean)
        ids = self.read_ids(self.path_source)

        # Create and save test data
        test_ids = self.create_and_save(ids, self.test_size, self.path_source,
                                           self.path_test)

        # Create and save validation data after excluding test ids
        unused_ids = [id for id in ids if id not in test_ids]
        validation_ids = self.create_and_save(unused_ids, self.validation_size,
                                                 self.path_source, self.path_validation)

        # Create and save training data after excluding both test and
        # validation ids
        unused_ids = [id for id in unused_ids if
                      id not in validation_ids and id not in test_ids]
        self.copy_samples(unused_ids, self.path_source, self.path_train)


class RefinedMPIIDatasetSplitFactory(DatasetSplitFactory):
    def __init__(self, test_person_identifiers, **kwargs):
        super().__init__(**kwargs)
        self.test_person_identifiers = test_person_identifiers

    def select_and_save(self, all_ids, prefix_list, from_path, to_path):
        test_ids = [id for id in all_ids if id[:3] in prefix_list]
        self.copy_samples(test_ids, from_path, to_path)
        return test_ids

    def run_for_person_identifiers(self, test_person_identifiers=list()):
        # Get all ids from the source folder (without suffix or _clean)
        ids = self.read_ids(self.path_source)

        # Create and save test data
        test_ids = self.select_and_save(ids, test_person_identifiers, self.path_source, self.path_test)

        # Create and save training data after excluding both test and
        # validation ids
        unused_ids = [id for id in ids if id not in test_ids]
        self.copy_samples(unused_ids, self.path_source, self.path_train)

    def run(self):
        self.run_for_person_identifiers(self.test_person_identifiers)


class MPIIDatasetSplitFactory(DatasetSplitFactory):
    def __init__(self, test_person_identifiers, **kwargs):
        super().__init__(**kwargs)
        self.test_person_identifiers = test_person_identifiers

    def run(self):
        n_train, n_test = self.run_for_person_identifiers(self.test_person_identifiers)
        print("Written train / test: {} / {}".format(n_train, n_test))

    def write_all(self, data, person_identifier, out_file):
        n = 0
        g = out_file.create_group(person_identifier)
        for attr in data[person_identifier]:
            d = data[person_identifier][attr]
            g.create_dataset(attr, data=d)
            # for i in data[attr]:
            #     out_file[attr].write(data[attr][i])
        n += data[person_identifier]['gaze'].shape[0]
        return n

    def run_for_person_identifiers(self, test_person_identifiers):
        import h5py
        file_train = h5py.File(self.path_train, 'w')
        file_test = h5py.File(self.path_test, 'w')
        n_train = 0
        n_test = 0

        with h5py.File(self.path_source, 'r') as hf:
            person_identifiers = hf.keys()
            for person_identifier in person_identifiers:
                if person_identifier in test_person_identifiers:
                    n_test += self.write_all(hf, person_identifier, file_test)
                else:
                    n_train += self.write_all(hf, person_identifier, file_train)

        file_train.close()
        file_test.close()

        return n_train, n_test


def run_refined_m2u():
    test_ids = ["p{}".format(i) for i in map(lambda s: str(s).zfill(2), range(12, 15))]
    factory = RefinedMPIIDatasetSplitFactory(
        path_source=os.path.join(BASE_DATA_DIR, "refined_MPII2Unity/"),
        path_train="../data/refined_MPII2Unity_Train/",
        path_validation=None,
        path_test="../data/refined_MPII2Unity_Test/",
        test_person_identifiers=test_ids,
        id_pattern=r'(p\d\d_\d+).jpg'
    )
    factory.run()


def run_refined_u2m():
    factory = StandardDatasetSplitFactory(
        path_source=os.path.join(BASE_DATA_DIR, "refined_Unity2MPII/"),
        path_train="../data/refined_Unity2MPII_Train/",
        path_validation="../data/refined_Unity2MPII_Val/",
        path_test="../data/refined_Unity2MPII_Test/",
        test_size=10000,
        validation_size=10000,
        id_pattern=r'(\d+).jpg'
    )
    factory.run()


def run_unityeyes():
    factory = StandardDatasetSplitFactory(
        path_source=os.path.join(BASE_DATA_DIR, "UnityEyes"),
        path_train="../data/UnityEyesTrain/",
        path_validation="../data/UnityEyesVal/",
        path_test="../data/UnityEyesTest/",
        test_size=10000,
        validation_size=10000,
        id_pattern=r'(\d+)\.jpg'
    )
    factory.run()


def run_refined_m():
    test_ids = ["p{}".format(i) for i in map(lambda s: str(s).zfill(2), range(12, 15))]
    factory = MPIIDatasetSplitFactory(
        path_source=os.path.join(BASE_DATA_DIR, "MPIIFaceGaze/single-eye-right_zhang.h5"),
        path_train="../data/MPIIFaceGaze/train-right.h5",
        path_validation=None,
        path_test="../data/MPIIFaceGaze/test-right.h5",
        test_person_identifiers=test_ids,
        id_pattern=None
    )
    factory.run()


if __name__ == "__main__":
    # run_unityeyes()
    run_refined_u2m()
    run_refined_m2u()
    # run_refined_m()

