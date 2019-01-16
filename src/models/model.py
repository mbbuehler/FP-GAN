import tensorflow as tf

import util.ops as ops
import util.utils as utils
from models.generator import Generator
from models.discriminator import Discriminator
from input.dataset_manager import DatasetManager
from util.enum_classes import DatasetClass as DS
from util.enum_classes import Mode


REAL_LABEL = 0.9


class CycleGAN:
    def __init__(self,
                 S_train_file='',
                 R_train_file='',
                 batch_size=1,
                 image_size=(72, 120),
                 use_lsgan=True,
                 norm='instance',
                 rgb=True,
                 lambda1=10,
                 lambda2=10,
                 lambdas_features={"identity": 0, "gaze": 0, "landmarks": 0},
                 learning_rate=2e-4,
                 beta1=0.5,
                 ngf=64,
                 tf_session=None,
                 filter_gaze=False,
                 ege_config=None
                 ):
        """
        Args:
          S_train_file: string UnityEyes folder
          R_train_file: string MPIIGaze h5 File
          batch_size: integer, batch size
          image_size: list(height, width)
          lambda1: integer, weight for forward cycle loss (X->Y->X)
          lambda2: integer, weight for backward cycle loss (Y->X->Y)
          lambdas_features: dict lambdas for feature loss. keys:
            "identity", "gaze", "landmarks"
          use_lsgan: boolean
          norm: 'instance' or 'batch'
          learning_rate: float, initial learning rate for Adam
          beta1: float, momentum term of Adam
          ngf: number of gen filters in first conv layer
          tf_session: tensorflow session. Needed for loading data sources.
        """
        self.lambda1 = lambda1
        self.lambda2 = lambda2
        # assert 'identity' in self.lambdas_features.keys()
        self.lambdas_features = lambdas_features
        self.use_lsgan = use_lsgan
        use_sigmoid = not use_lsgan
        self.batch_size = batch_size
        self.image_size = image_size
        self.rgb = rgb
        self.learning_rate = learning_rate
        self.beta1 = beta1
        self.S_train_file = S_train_file
        self.R_train_file = R_train_file
        self.tf_session = tf_session
        if rgb:
            input_shape = [batch_size, *image_size, 3]
        else:
            input_shape = [batch_size, *image_size, 1]

        self.is_training = tf.placeholder_with_default(True, shape=[],
                                                       name='gan_is_training')

        self.G = Generator('G', self.is_training, ngf=ngf, norm=norm,
                           image_size=image_size, rgb=rgb)
        self.D_R = Discriminator('D_R',
                                 self.is_training, norm=norm,
                                 use_sigmoid=use_sigmoid)
        self.F = Generator('F', self.is_training, ngf=ngf, norm=norm,
                           image_size=image_size, rgb=rgb)
        self.D_S = Discriminator('D_S',
                                 self.is_training, norm=norm,
                                 use_sigmoid=use_sigmoid)

        self.fake_s = tf.placeholder(tf.float32,
                                     shape=input_shape)
        self.fake_r = tf.placeholder(tf.float32,
                                     shape=input_shape)
        if self.S_train_file != '' and self.R_train_file != '':
            self.S_iterator = DatasetManager.get_dataset_iterator_for_path(
                self.S_train_file,
                image_size,
                batch_size,
                rgb=rgb,
                shuffle=True,
                repeat=True,
                do_augmentation=False,
                dataset_class=DS.UNITY,
                filter_gaze=filter_gaze
            )
            self.R_iterator = DatasetManager.get_dataset_iterator_for_path(
                self.R_train_file,
                image_size,
                batch_size,
                rgb=rgb,
                shuffle=True,
                repeat=True,
                do_augmentation=False,
                dataset_class=DS.MPII,
                filter_gaze=filter_gaze
            )
        if self.lambdas_features['gaze'] > 0:
            from models.gazenet import GazeNet
            self.gazenet = GazeNet(
                batch_size=batch_size,
                image_size=image_size,
                learning_rate=None,
                beta1=None,
                beta2=None,
                **ege_config
            )
        if self.lambdas_features['landmarks'] > 0:
            from models.elg import ELG
            self.elg = ELG(num_feature_maps=64)

    def model(self, fake_input=False):
        if fake_input:
            if self.rgb:
                shape = [self.batch_size, *self.image_size, 3]
            else:
                shape = [self.batch_size, *self.image_size, 1]
            s = tf.placeholder(tf.float32, shape)
            r = tf.placeholder(tf.float32, shape)
        else:
            S_input_batch = self.S_iterator.get_next()
            s = S_input_batch['eye']
            R_input_batch = self.R_iterator.get_next()
            r = R_input_batch['eye']

        # why don't we feed G(x) / F(y) here?
        cycle_loss = self.cycle_consistency_loss(self.G, self.F, s, r)

        # X -> Y
        fake_r = self.G(s)
        G_gan_loss = self.generator_loss(self.D_R, fake_r,
                                         use_lsgan=self.use_lsgan)
        G_feature_loss = self.get_feature_loss(s, fake_r, 'G')
        G_loss = G_gan_loss + cycle_loss + G_feature_loss
        D_R_loss = self.discriminator_loss(self.D_R, r, self.fake_r,
                                           use_lsgan=self.use_lsgan)

        # Y -> X
        fake_s = self.F(r)
        F_gan_loss = self.generator_loss(self.D_S, fake_s,
                                         use_lsgan=self.use_lsgan)
        F_feature_loss = self.get_feature_loss(r, fake_s, 'F')
        F_loss = F_gan_loss + cycle_loss + F_feature_loss
        D_S_loss = self.discriminator_loss(self.D_S, s, self.fake_s,
                                           use_lsgan=self.use_lsgan)

        # summary
        tf.summary.histogram('D_R/true', self.D_R(r))
        tf.summary.histogram('D_R/fake', self.D_R(self.G(s)))
        tf.summary.histogram('D_S/true', self.D_S(s))
        tf.summary.histogram('D_S/fake', self.D_S(self.F(r)))

        tf.summary.scalar('loss/G', G_gan_loss)
        tf.summary.scalar('loss/G_feature', G_feature_loss)
        tf.summary.scalar('loss/D_R', D_R_loss)
        tf.summary.scalar('loss/F', F_gan_loss)
        tf.summary.scalar('loss/F_feature', F_feature_loss)
        tf.summary.scalar('loss/D_S', D_S_loss)
        tf.summary.scalar('loss/cycle', cycle_loss)

        tf.summary.image('S/input', utils.batch_convert2int(s))
        tf.summary.image('S/generated', utils.batch_convert2int(self.G(s)))
        tf.summary.image('S/reconstruction',
                         utils.batch_convert2int(self.F(self.G(s))))
        tf.summary.image('R/input', utils.batch_convert2int(r))
        tf.summary.image('R/generated', utils.batch_convert2int(self.F(r)))
        tf.summary.image('R/reconstruction',
                         utils.batch_convert2int(self.G(self.F(r))))

        return G_loss, D_R_loss, F_loss, D_S_loss, fake_r, fake_s

    def optimize(self, G_loss, D_R_loss, F_loss, D_S_loss, n_steps=200000):
        def make_optimizer(loss, variables, name='Adam'):
            """ Adam optimizer with learning rate 0.0002 for the first 100k
            steps (~100 epochs)
                and a linearly decaying rate that goes to zero over
                the next 100k steps
            """
            # why can global step be 0 here? Does it automatically
            # increase after each optimisation step?
            global_step = tf.Variable(0, trainable=False)
            starter_learning_rate = self.learning_rate
            end_learning_rate = 0.0
            start_decay_step = int(n_steps / 2)
            decay_steps = n_steps - start_decay_step
            beta1 = self.beta1
            learning_rate = (
                tf.where(
                    tf.greater_equal(global_step, start_decay_step),
                    tf.train.polynomial_decay(starter_learning_rate,
                                              global_step - start_decay_step,
                                              decay_steps, end_learning_rate,
                                              power=1.0),
                    starter_learning_rate
                )

            )
            tf.summary.scalar('learning_rate/{}'.format(name), learning_rate)

            learning_step = (
                tf.train.AdamOptimizer(learning_rate, beta1=beta1, name=name)
                    .minimize(loss, global_step=global_step,
                              var_list=variables)
            )
            return learning_step

        G_optimizer = make_optimizer(G_loss, self.G.variables, name='Adam_G')
        D_Y_optimizer = make_optimizer(D_R_loss, self.D_R.variables,
                                       name='Adam_D_R')
        F_optimizer = make_optimizer(F_loss, self.F.variables, name='Adam_F')
        D_X_optimizer = make_optimizer(D_S_loss, self.D_S.variables,
                                       name='Adam_D_S')

        with tf.control_dependencies(
                [G_optimizer, D_Y_optimizer, F_optimizer, D_X_optimizer]):
            return tf.no_op(name='optimizers')

    def discriminator_loss(self, D, y, fake_y, use_lsgan=True):
        """ Note: default: D(y).shape == (batch_size,5,5,1),
                           fake_buffer_size=50, batch_size=1
        Args:
          D: discriminator object
          y: 4D tensor (batch_size, image_size, image_size, 3)
          use_lsgan: use least-squares loss instead of cross-entropy
        Returns:
          loss: scalar
        """
        if use_lsgan:
            # use mean squared error
            error_real = tf.reduce_mean(
                tf.squared_difference(D(y), REAL_LABEL))
            error_fake = tf.reduce_mean(tf.square(D(fake_y)))
        else:
            # use cross entropy
            error_real = -tf.reduce_mean(ops.safe_log(D(y)))
            error_fake = -tf.reduce_mean(ops.safe_log(1 - D(fake_y)))
        loss = (error_real + error_fake) / 2
        return loss

    def generator_loss(self, D, fake_y, use_lsgan=True):
        """  fool discriminator into believing that G(x) is real
        """
        if use_lsgan:
            # use mean squared error
            loss = tf.reduce_mean(tf.squared_difference(D(fake_y), REAL_LABEL))
        else:
            # heuristic, non-saturating loss
            loss = -tf.reduce_mean(ops.safe_log(D(fake_y))) / 2
        return loss

    def cycle_consistency_loss(self, G, F, x, y):
        """ cycle consistency loss (L1 norm)
        """
        forward_loss = tf.reduce_mean(tf.abs(F(G(x)) - x))
        backward_loss = tf.reduce_mean(tf.abs(G(F(y)) - y))
        loss = self.lambda1 * forward_loss + self.lambda2 * backward_loss
        return loss

    def get_feature_loss(self, x, fake_y, generator_name):
        """
        Placeholder only
        :param x: real input
        :param fake_y: translated x
        :return:
        """
        loss = 0
        if self.lambdas_features["identity"] > 0:
            id_loss = self._identity_transform_loss(x, fake_y, generator_name)
            loss += id_loss
        if self.lambdas_features["gaze"] > 0:
            gaze_loss = self._gaze_transform_loss(x, fake_y, generator_name)
            loss += gaze_loss
        if self.lambdas_features["landmarks"] > 0:
            lm_loss = self._landmarks_transform_loss(x, fake_y, generator_name)
            loss += lm_loss
        return loss

    def _identity_transform_loss(self, x, fake_y, generator_name):
        """
        L1 Identity transform loss. This ensures that fake_y is
        not too different from x
        :param x: input to generator
        :param fake_y: G(x)
        :return:
        """
        x_grayscale = tf.reduce_mean(x, 3)
        fake_y_grayscale = tf.reduce_mean(fake_y, 3)
        loss = tf.reduce_mean(tf.abs(fake_y_grayscale - x_grayscale))
        tf.summary.scalar('loss/{}/identity'.format(generator_name), loss)
        return self.lambdas_features['identity'] * loss

    def _gaze_transform_loss(self, x, fake_y, generator_name):
        """
        L2 transform loss on eye gaze. This ensures that fake_y is
        not too different from x
        :param x: input to generator
        :param fake_y: G(x)
        :return:
        """
        x_gaze = self.gazenet.forward(x, mode=Mode.TEST, is_training=False)
        fake_y_gaze = self.gazenet.forward(fake_y, mode=Mode.TEST, is_training=False)
        loss = tf.reduce_mean(tf.squared_difference(x_gaze, fake_y_gaze))
        tf.summary.scalar('loss/{}/gaze'.format(generator_name), loss)
        return self.lambdas_features['gaze'] * loss

    def _landmarks_transform_loss(self, x, fake_y, generator_name):
        # for image size 36,60 we yield 60
        normalisation_constant = max(self.image_size)
        x_output, _, _ = self.elg.build_model(x)
        fake_y_output, _, _ = self.elg.build_model(fake_y)
        loss = tf.reduce_mean(tf.squared_difference(x_output['landmarks']/normalisation_constant, fake_y_output['landmarks']/normalisation_constant))
        tf.summary.scalar('loss/{}/landmarks'.format(generator_name), loss)
        return self.lambdas_features['landmarks'] * loss