
# based on the codes from  [Sadeghi and Larsson, 2019]

import numpy as np
import tensorflow as tf

###############################  CNN-GAN of Table 1 ###############################
class GAN_CNN(object):
    def __init__(self, k, n, seed=None, filename=None):
        self.k = k 
        self.n = n
        self.bits_per_symbol = self.k/self.n
        self.M = 2**self.k
        self.seed = seed
        self.graph = None  
        self.sess = None  
        self.vars = None 
        self.saver = None 
        self.constellations = None
        self.blers = None
        self.create_graph()
        self.create_session()
        if filename is not None:    
            self.load(filename)       
        return
    
    def create_graph(self):
        '''This function creates the computation graph of the autoencoder'''
        self.graph = tf.Graph()        
        with self.graph.as_default():  
            tf.set_random_seed(self.seed)
            batch_size = tf.placeholder(tf.int32, shape=(), name='batchsize')
            is_training = tf.placeholder(tf.bool, name='istraining')
            dr_out = tf.placeholder(tf.float32,shape=(), name='drout')
            # Transmitter
            s = tf.random_uniform(shape=[batch_size], minval=0, maxval=self.M, dtype=tf.int64)
            x = self.encoder(s)    
            
            ########generative network
            x_g = self.encoder_2(x)
            pp = tf.reduce_mean(x_g,0)

            # the attack vector
            p = tf.placeholder(tf.float32,shape=(None,2,self.n), name='pname') # batch * 2 * n is the shape of y and x.
            
            # Channel
            noise_std = tf.placeholder(tf.float32, shape=()) 
            noise = tf.random_normal(tf.shape(x), mean=0.0, stddev=noise_std)
            
            #clean signal
            y = x + noise + p
            
            
            ####### Perturbed Signal
            ep = tf.placeholder(tf.float32, shape=()) 
            y_perturbed = y + ep*pp
            #######
            
            # Receiver
            s_hat = self.decoder(y, dr_out, is_training)
            s_hat_p = self.decoder(y_perturbed,dr_out, is_training,True)
            
            
            #GAN loss
            d_loss_real = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=s_hat, labels=tf.one_hot(s,self.M)))
            d_loss_noise = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=s_hat_p, labels=tf.one_hot(s,self.M)))
            
            #Loss
            cross_entropy = tf.losses.sparse_softmax_cross_entropy(labels=s, logits=s_hat)

            d_loss =  d_loss_real+d_loss_noise
            g_loss = -d_loss_noise
            
            
            t_vars = tf.trainable_variables()
            d_vars = [var for var in t_vars if 'ds_' in var.name]
            g_vars = [var for var in t_vars if 'ge_' in var.name]
 
            # Performance metrics
            correct_predictions = tf.equal(tf.argmax(tf.nn.softmax(s_hat), axis=1), s)
            accuracy = tf.reduce_mean(tf.cast(correct_predictions, tf.float32))
            bler = 1-accuracy
            
            
            # Optimizer
            lr = tf.placeholder(tf.float32, shape=())    
            train_op = tf.train.AdamOptimizer(lr*10.0).minimize(cross_entropy)
            #consensus optimization
            train_op_g = self.conciliate(lr/10.0, d_loss, g_loss, d_vars,g_vars)
        
            # References to graph variables we need to access later 
            self.vars = {
                'accuracy': accuracy,
                'batch_size': batch_size,
                'bler': bler,
                'cross_entropy': cross_entropy,
                'd_loss':d_loss,
                'dr_out':dr_out,
                'is_training':is_training,
                'init': tf.global_variables_initializer(),
                'lr': lr,
                'noise_std': noise_std,
                'noise': noise,
                'p': p,
                's': s,
                's_hat': s_hat,
                'train_op': train_op,
                # 'train_op_d': train_op_d,
                'train_op_g': train_op_g,
                'x': x,
                'y': y,
                'x_g':x_g,
                'pp':pp,
                'ep':ep,
                
            }            
            self.saver = tf.train.Saver()
        return

######### consensus optimization
    def conciliate(self, learning_rate, d_loss, g_loss, d_vars, g_vars, global_step=None):
        optimizer = tf.train.RMSPropOptimizer(learning_rate)
        alpha = 0.1

        # Compute gradients
        d_grads = tf.gradients(d_loss, d_vars)
        g_grads = tf.gradients(g_loss, g_vars)

        # Merge variable and gradient lists
        variables = d_vars + g_vars
        grads = d_grads + g_grads

        # Reguliarizer
        reg = 0.5 * sum(
            tf.reduce_sum(tf.square(g)) for g in grads
        )
        # Jacobian times gradiant
        Jgrads = tf.gradients(reg, variables)

        # Gradient updates
        apply_vec = [
             (g + alpha * Jg, v)
             for (g, Jg, v) in zip(grads, Jgrads, variables) if Jg is not None
        ]

        train_op = optimizer.apply_gradients(apply_vec)

        return [train_op]
    
    def create_session(self):
        '''Create a session for the autoencoder instance with the compuational graph'''
        self.sess = tf.Session(graph=self.graph)      
        self.sess.run(self.vars['init'])
        return
    
    
    def encoder(self, input):
        '''The transmitter'''
        W = self.weight_variable((self.M,self.M))
        x = tf.nn.elu(tf.nn.embedding_lookup(W, input)) 
        x = tf.reshape(x,[-1,1,self.M])
        conv0 = tf.layers.conv1d(x, 16, 6, strides=1, padding='same', data_format='channels_last',
                             activation=tf.nn.relu, use_bias=True,
                             kernel_initializer=tf.glorot_uniform_initializer(seed=None, dtype=tf.float32),
                             trainable=True)
        flattened0 = tf.layers.flatten(conv0)
        x = tf.layers.dense(flattened0, 2*self.n, activation=None)
        x = tf.reshape(x, shape=[-1,2,self.n]) 
        #Average power normalization
        x = x/tf.sqrt(2*tf.reduce_mean(tf.square(x)))
        return x
    
    def decoder(self, input, dr_out, is_training,reuse=False):
        '''The Receiver'''
        with tf.variable_scope("decoder", reuse=reuse):
            reshaped = tf.reshape(input, shape=[-1,1,2,self.n])
            conv1 = tf.layers.conv2d(reshaped, 16, [2,3], strides=(1, 1), padding='same', name="ds_1",data_format='channels_last',
                                 activation=tf.nn.relu, use_bias=True,
                                 kernel_initializer=tf.glorot_uniform_initializer(seed=None, dtype=tf.float32),
                                 trainable=True)
            conv2 = tf.layers.conv2d(conv1, 8, [2,3], strides=(1, 1), padding='same', name="ds_2",data_format='channels_last',
                                 activation=tf.nn.relu, use_bias=True,
                                 kernel_initializer=tf.glorot_uniform_initializer(seed=None, dtype=tf.float32),
                                 trainable=True)
            drout = tf.layers.dropout(conv2, rate=dr_out, noise_shape=None,training=is_training, name='ds_dropou1')
            flattened = tf.layers.flatten(drout)
            dense1 = tf.layers.dense(flattened, 2*self.M, name="ds_4", activation=tf.nn.relu)
            y = tf.layers.dense(dense1, self.M, activation=None)
            return y

########generative network architecture
    def encoder_2(self, input,reuse=False):
        '''The transmitter'''
        with tf.variable_scope("encoder_2", reuse=reuse):
            x= input
              
            
            conv0 = tf.layers.conv1d(x, 16*8, 6, strides=1, padding='same', name="ge_1",data_format='channels_last',
                                  activation=tf.nn.relu, use_bias=True,
                                  kernel_initializer=tf.glorot_uniform_initializer(seed=None, dtype=tf.float32),
                                  trainable=True)
            bn0 = tf.layers.batch_normalization(conv0, training=True, name='ge_bn1')
            conv1 = tf.layers.conv1d(bn0, 16*8, 6, strides=1, padding='same', name="ge_2",data_format='channels_last',
                          activation=tf.nn.relu, use_bias=True,
                          kernel_initializer=tf.glorot_uniform_initializer(seed=None, dtype=tf.float32),
                          trainable=True)
            bn1 = tf.layers.batch_normalization(conv1, training=True, name='ge_bn2')
            

                    
            flattened0 = tf.layers.flatten(bn1)
            x = tf.layers.dense(flattened0, 2*self.n, name="ge_12",activation=None)
            x = tf.reshape(x, shape=[-1,2,self.n]) 
            #normalization
            x = x/tf.sqrt(2*tf.reduce_mean(tf.square(x)))
            return x

    def EbNo2Sigma(self, ebnodb):
        '''Convert Eb/No in dB to noise standard deviation'''
        ebno = 10**(ebnodb/10)
        return 1/np.sqrt(2*self.bits_per_symbol*ebno) 
    
    def gen_feed_dict(self, is_training,dr_out, perturbation, batch_size, ebnodb, lr, ep):
        '''Generate a feed dictionary for training and validation'''      
        return {
            self.vars['is_training']: is_training,
            self.vars['dr_out']: dr_out,
            self.vars['p']: perturbation,
            self.vars['batch_size']: batch_size,
            self.vars['noise_std']: self.EbNo2Sigma(ebnodb),
            self.vars['lr']: lr,
            self.vars['ep']: ep,
            
        }    
    
    
    def load(self, filename):
        '''Load a pre_trained model'''
        return self.saver.restore(self.sess, filename)
    
    def save(self, filename):
        '''Save the current model'''
        return self.saver.save(self.sess, filename)  
    
    def test_step(self, is_training, dr_out, p, batch_size, ebnodb,ep):
        '''Compute the BLER over a single batch and Eb/No'''
        bler = self.sess.run(self.vars['bler'], feed_dict=self.gen_feed_dict(is_training, dr_out, p, batch_size, ebnodb, 0,ep))  
        return bler
    
    def transmit(self, s):
        '''Returns the transmitted sigals corresponding to message indices'''
        return self.sess.run(self.vars['x'], feed_dict={self.vars['s']: s})
       
    def train(self, is_training, dr_out ,p, training_params, validation_params,ep):  
        '''Training and validation loop'''
        for index, params in enumerate(training_params):            
            batch_size, lr, ebnodb, iterations = params            
            print('\nBatch Size: ' + str(batch_size) +
                  ', Learning Rate: ' + str(lr) +
                  ', EbNodB: ' + str(ebnodb) +
                  ', Iterations: ' + str(iterations))
            
            val_size, val_ebnodb, val_steps = validation_params[index]
            
            for i in range(iterations):
                self.train_step(is_training, dr_out, p, batch_size, ebnodb, lr,ep)    
                if (i%val_steps==0):
                    bler = self.sess.run(self.vars['bler'], feed_dict=self.gen_feed_dict(is_training, dr_out , p,val_size, val_ebnodb, lr,ep))
                    pp = self.sess.run(self.vars['pp'], feed_dict=self.gen_feed_dict(is_training, dr_out , p,val_size, val_ebnodb, lr,ep))
                    print(bler)                           
        return pp      
    
    def train_step(self, is_training, dr_out , p, batch_size, ebnodb, lr,ep):
        '''A single training step'''
        self.sess.run(self.vars['train_op_g'], feed_dict=self.gen_feed_dict(is_training, dr_out , p, batch_size, ebnodb, lr,ep))
        self.sess.run(self.vars['train_op'], feed_dict=self.gen_feed_dict(is_training, dr_out , p, batch_size, ebnodb, lr,ep)) #self.sess.run(train_op, feed_dict=self.gen_feed_dict(batch_size, ebnodb, lr))#s
        
        return 
    
    def weight_variable(self, shape):
        '''Xavier-initialized weights optimized for ReLU Activations'''
        (fan_in, fan_out) = shape
        low = np.sqrt(6.0/(fan_in + fan_out)) 
        high = -np.sqrt(6.0/(fan_in + fan_out))
        return tf.Variable(tf.random_uniform(shape, minval=low, maxval=high, dtype=tf.float32))
    
    
    def bler_sim_attack_AWGN(self, is_training, dr_out , p, PSR_dB, ebnodbs, batch_size, iterations,ep):
        '''Generate the BLER for 4 cases: 1) no attack, 2) synchronous adversarial attack, 3) non-synchronous adversarial attack and 4) jamming attack'''
        PSR = 10**(PSR_dB/10)
        scale_factor = np.sqrt( (PSR * self.n) / (np.linalg.norm(p)**2 + 0.00000001) ) # note that self.n is the power of the x, as designed by Jakob
        p = scale_factor * p
        
        BLER_no_attack = np.zeros_like(ebnodbs)
        BLER_attack_rolled = np.zeros_like(ebnodbs)
        BLER_jamming = np.zeros_like(ebnodbs)

        for i in range(iterations):
            # No attack - clean case
            bler = np.array([self.sess.run(self.vars['bler'],
                            feed_dict=self.gen_feed_dict(is_training, dr_out , np.zeros([1,2,self.n]), batch_size, ebnodb, 0,ep)) for ebnodb in ebnodbs]) #bler = np.array([self.sess.run(self.vars['bler'],feed_dict=self.gen_feed_dict(p, batch_size, ebnodb, lr=0)) for ebnodb in ebnodbs])
            BLER_no_attack = BLER_no_attack + bler/iterations
            # attack - rolled attack - nonsynchronous
            p_rolled = np.roll(p, int(np.ceil(np.random.uniform(0,self.n))))
            bler_attack_rolled = np.array([self.sess.run(self.vars['bler'],
                            feed_dict=self.gen_feed_dict(is_training, dr_out ,p_rolled,batch_size, ebnodb, 0,ep)) for ebnodb in ebnodbs]) # I think lr=0 is equal to is_training=False
            BLER_attack_rolled = BLER_attack_rolled + bler_attack_rolled/iterations
            # Jamming attack
            normal_noise_as_jammer = np.random.normal(0,1,p.shape)
            jamming = np.linalg.norm(p) * (1 / np.linalg.norm(normal_noise_as_jammer)) * normal_noise_as_jammer
            bler_jamming= np.array([self.sess.run(self.vars['bler'],
                            feed_dict=self.gen_feed_dict(is_training, dr_out, jamming,batch_size, ebnodb, 0,ep)) for ebnodb in ebnodbs]) # I think lr=0 is equal to is_training=False
            BLER_jamming = BLER_jamming + bler_jamming/iterations
        return BLER_no_attack, BLER_attack_rolled, BLER_jamming
