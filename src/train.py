import logging
import os

import tensorflow as tf
from datetime import datetime

from models.model import CycleGAN
from util.utils import ImagePool

FLAGS = tf.flags.FLAGS

tf.flags.DEFINE_integer('batch_size', 8, 'batch size, default: 1')
tf.flags.DEFINE_integer('image_width', 120, 'default: 120')
tf.flags.DEFINE_integer('image_height', 72, 'default: 72')
tf.flags.DEFINE_bool('use_lsgan', True,
                     'use lsgan (mean squared error) or cross entropy loss, default: True')
tf.flags.DEFINE_string('norm', 'instance',
                       '[instance, batch] use instance norm or batch norm, default: instance')
tf.flags.DEFINE_integer('lambda1', 10,
                        'weight for forward cycle loss (X->Y->X), default: 10')
tf.flags.DEFINE_integer('lambda2', 10,
                        'weight for backward cycle loss (Y->X->Y), default: 10')
tf.flags.DEFINE_float('learning_rate', 2e-4,
                      'initial learning rate for Adam, default: 0.0002')
tf.flags.DEFINE_float('beta1', 0.5,
                      'momentum term of Adam, default: 0.5')
tf.flags.DEFINE_float('pool_size', 50,
                      'size of image buffer that stores previously generated images, default: 50')
tf.flags.DEFINE_integer('ngf', 32,
                        'number of gen filters in first conv layer, default: 64')
tf.flags.DEFINE_string('X', '../data/UnityEyes',
                       'X tfrecords file for training, default: ../data/tfrecords/apple.tfrecords')
tf.flags.DEFINE_string('Y', '../data/MPIIFaceGaze/single-eye_zhang.h5',
                       'Y tfrecords file for training, default: ../data/tfrecords/orange.tfrecords')
tf.flags.DEFINE_string('load_model', None,
                       'folder of saved model that you wish to continue training (e.g. 20170602-1936), default: None')
tf.flags.DEFINE_integer('n_steps', 200000,
                       'number of steps to train. Half of the steps will be trained with a fix learning rate, the second half with linearly decaying LR.')
tf.flags.DEFINE_string('data_format', 'NHWC',
                       'NHWC or NCHW. default: NHWC')  # Important: This implementation does not yet support NCHW, so stick to NHWC!


def train():
    if FLAGS.load_model is not None:
        checkpoints_dir = "../checkpoints/" + FLAGS.load_model.lstrip(
            "checkpoints/")
    else:
        current_time = datetime.now().strftime("%Y%m%d-%H%M")
        checkpoints_dir = "../checkpoints/{}".format(current_time)
    try:
        os.makedirs(checkpoints_dir)
    except os.error:
        pass

    graph = tf.Graph()

    image_size = [FLAGS.image_height, FLAGS.image_width]

    with tf.Session(graph=graph) as sess:
        with graph.as_default():
            cycle_gan = CycleGAN(
                X_train_file=FLAGS.X,
                Y_train_file=FLAGS.Y,
                batch_size=FLAGS.batch_size,
                image_size=image_size,
                use_lsgan=FLAGS.use_lsgan,
                norm=FLAGS.norm,
                lambda1=FLAGS.lambda1,
                lambda2=FLAGS.lambda2,
                learning_rate=FLAGS.learning_rate,
                beta1=FLAGS.beta1,
                ngf=FLAGS.ngf,
                tf_session=sess,
            )
            G_loss, D_Y_loss, F_loss, D_X_loss, fake_y, fake_x = cycle_gan.model()
            optimizers = cycle_gan.optimize(G_loss, D_Y_loss, F_loss, D_X_loss, n_steps=FLAGS.n_steps)

            summary_op = tf.summary.merge_all()
            train_writer = tf.summary.FileWriter(checkpoints_dir, graph)
            saver = tf.train.Saver()

        if FLAGS.load_model is not None:
            checkpoint = tf.train.get_checkpoint_state(checkpoints_dir)
            meta_graph_path = checkpoint.model_checkpoint_path + ".meta"
            restore = tf.train.import_meta_graph(meta_graph_path)
            restore.restore(sess, tf.train.latest_checkpoint(checkpoints_dir))
            step = int(meta_graph_path.split("-")[2].split(".")[0])
        else:
            sess.run(tf.global_variables_initializer())
            step = 0

        coord = tf.train.Coordinator()
        threads = tf.train.start_queue_runners(sess=sess, coord=coord)

        try:
            fake_Y_pool = ImagePool(FLAGS.pool_size)
            fake_X_pool = ImagePool(FLAGS.pool_size)

            while step < FLAGS.n_steps and not coord.should_stop():
                # get previously generated images
                fake_y_val, fake_x_val = sess.run([fake_y, fake_x])

                _, G_loss_val, D_Y_loss_val, F_loss_val, D_X_loss_val, summary = (
                      sess.run(
                          [optimizers, G_loss, D_Y_loss, F_loss, D_X_loss, summary_op],
                          feed_dict={cycle_gan.fake_y: fake_Y_pool.query(fake_y_val),
                                     cycle_gan.fake_x: fake_X_pool.query(fake_x_val)}
                      )
                )

                train_writer.add_summary(summary, step)
                train_writer.flush()

                n_info_steps = 100
                if step % n_info_steps == 0:
                    # coord.
                    logging.info('-----------Step %d:-------------' % step)
                    logging.info('  Time: {}'.format(
                        datetime.now().strftime('%b-%d-%I%M%p-%G')))
                    logging.info('  G_loss   : {}'.format(G_loss_val))
                    logging.info('  D_Y_loss : {}'.format(D_Y_loss_val))
                    logging.info('  F_loss   : {}'.format(F_loss_val))
                    logging.info('  D_X_loss : {}'.format(D_X_loss_val))

                if step % 10000 == 0:
                    save_path = saver.save(sess,
                                           checkpoints_dir + "/model.ckpt",
                                           global_step=step)
                    logging.info("Model saved in file: %s" % save_path)

                step += 1
        except KeyboardInterrupt:
            logging.info('Interrupted')
            coord.request_stop()
        except Exception as e:
            coord.request_stop(e)
        finally:
            save_path = saver.save(sess, checkpoints_dir + "/model.ckpt",
                                   global_step=step)
            logging.info("Model saved in file: %s" % save_path)
            # When done, ask the threads to stop.
            coord.request_stop()
            coord.join(threads)


def main(unused_argv):
    train()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    tf.app.run()
