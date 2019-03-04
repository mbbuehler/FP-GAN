"""Translate images from original to refined
An example of command-line usage is:
CUDA_VISIBLE_DEVICES=0 python run/run_fpgan_translations.py
    --config ../config/fpgan_basic.ini
    --section 20181123-1412
    --direction R2S

"""
import logging

import tensorflow as tf

from models.fpgan_export import GeneratorExport
from models.fpgan_inference import GeneratorInference
from util.config_loader import Config
from util.enum_classes import TranslationDirection as Direction, \
    DatasetClass as DS


def run_export(cfg, S2R=True):
    """
    Exports the model in given direction (default S2R).
    :param cfg: config
    :param S2R: Export from Unity (synthetic) to MPII (real)
        or the other way round
    :return:
    """
    logging.info("Exporting model from {}...".
                 format(cfg.get("checkpoint_folder")))
    default_args = dict(
        checkpoint_dir=cfg.get("checkpoint_folder"),
        image_size=[cfg.get('image_height'),
                  cfg.get('image_width')],
        batch_size=cfg.get("batch_size_inference"),
        norm=cfg.get("norm"),
        ngf=cfg.get("ngf"),
        rgb=cfg.get("rgb")
    )

    generator_export = GeneratorExport(**default_args)

    if S2R:
        logging.info('Exporting S2R model...')
        generator_export.run(
            model_name=cfg.get("model_name_s2r"),
            S2R=True)
    else:
        logging.info('Exporting R2S model...')
        generator_export.run(
            model_name=cfg.get("model_name_r2s"),
            S2R=False)


def run_inference(cfg, S2R=True):
    """
    Translates images
    pre: there exists exported model using the same batch size
    :param cfg: config
    :param S2R: Unity to MPII
    :return:
    """
    # Variables used for both directions
    batch_size = cfg.get('batch_size_inference')
    image_size = [cfg.get('image_height'),
                  cfg.get('image_width')]
    rgb = cfg.get('rgb')

    shared_args = dict(
        batch_size=batch_size, image_size=image_size, rgb=rgb
    )
    # Variables dependent on direction
    if S2R:
        path_in = cfg.get("S")
        model_path = cfg.get("path_model_s2r")
        output_folder = cfg.get('path_refined_r2s')
        inference = GeneratorInference(path_in=path_in, model_path=model_path, output_folder=output_folder,
                                       dataset_class=DS.UNITY, **shared_args)
        inference.run()
    else:
        path_in = cfg.get("R")
        model_path = cfg.get("path_model_r2s")
        output_folder = cfg.get('path_refined_s2r')
        inference = GeneratorInference(path_in=path_in, model_path=model_path, output_folder=output_folder,
                                       dataset_class=DS.MPII, **shared_args)
        inference.run()


def main():
    FLAGS = tf.flags.FLAGS
    tf.flags.DEFINE_string('config', None, 'input configuration')
    tf.flags.DEFINE_string('section', 'DEFAULT', 'input configuration')
    tf.flags.DEFINE_string('direction', 'S2R', 'input configuration')

    # Load the config variables
    cfg = Config(FLAGS.config, FLAGS.section)

    if FLAGS.direction in [Direction.S2R, Direction.BOTH]:
        run_export(cfg, S2R=True)
        run_inference(cfg, S2R=True)
    if FLAGS.direction in [Direction.R2S, Direction.BOTH]:
        run_export(cfg, S2R=False)
        run_inference(cfg, S2R=False)
    if FLAGS.direction not in Direction.get_all():
        print("Invalid direction: {}".format(FLAGS.direction))
        print("Direction must be one of: {}".format(", ".join(Direction().get_all())))
        exit()


if __name__ == '__main__':
    main()
