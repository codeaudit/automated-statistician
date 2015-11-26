"""
gaussian_process.py

Author: Rui Shu

This module implements Gaussian process regression, leveraging TensorFlow's
automatic differentiation for length scale learning and gridless acquisition
function optimization.
"""
__docformat__ = "restructuredtext en"

import tensorflow as tf
import numpy as np
from kernels import *
import time

@tf.RegisterGradient("MatrixDeterminant")
def _MatrixDeterminant(op, grad):
    """Gradient for MatrixDeterminant."""
    return grad * op.outputs[0] * tf.transpose(tf.matrix_inverse(op.inputs[0]))

class GaussianProcess(object):
    """ Gaussian Process Class
    
    Guassian process regression using tensorflow. 
    """
    def __init__(self, n_dim, kernel, n_epochs, batch_size, noise=0.0,
                 train_noise=False,
                 optimizer=tf.train.GradientDescentOptimizer(0.01),
                 verbose=0):
        """ Initialize parameters for Gaussian process object

        Parameters
        ----------
        n_epochs : int
            The number of epochs in stochastic gradient descend for fitting the
            GP kernel's length scale and amplitude.
        batch_size : int
            The number of data points to be fed during each step of stochastic
            gradient descent.
        n_dim : int
            The number of dimensions in the parameter space.
        kernel : Kernel object
            The covariance function to be used for GP regression
        noise : float32
            The noise hyperparameter for GP regression
        train_noise : bool
            Determines whether sgd will also optimize the loss function
            w.r.t. the noise hyperparameter in addition to the length scales.
        optimizer : tf.train.Gradient
            One of any gradient descent methods. Default to using basic sgd.
        verbose : int 
            Allows for different levels of verbosity for debugging purposes
        """
        # Save settings for kernel
        self.n_dim = n_dim
        self.kernel = kernel
        self.noise = tf.Variable(noise)
        # Save settings for gradient descend algorithm
        self.n_epochs = n_epochs
        self.batch_size = batch_size
        self.train_noise = train_noise
        self.optimizer = optimizer
        self.verbose = verbose
        # Create placeholder for observed data to be used in GP training of
        # length scales and/or noise parameter
        self.X = tf.placeholder(tf.float32, [None, n_dim])
        self.y = tf.placeholder(tf.float32, [None, 1])
        # Compute the covariance matrix and its inverse
        self.K = (
            self.kernel.covariance(self.X) + 
            tf.square(self.noise) * tf.diag(
                tf.ones(
                    tf.pack([tf.shape(self.X)[0]])
                )
            )
        )
        self.K_inv = tf.matrix_inverse(self.K)
        # Determine the gp negative log marginal likelihood
        self.cost = (
            tf.matmul(tf.matmul(tf.transpose(self.y), self.K_inv),
                      self.y)
            + tf.log(tf.matrix_determinant(self.K))
        )
        # Define the training operation for grad descend
        var_list = [self.kernel.length_scales]
        if self.train_noise:
            var_list.append(self.noise)
        self.train = self.optimizer.minimize(self.cost, var_list=var_list)
        # Initialize the TensorFlow session
        self.sess = tf.Session(
            config=tf.ConfigProto(
                inter_op_parallelism_threads=1, intra_op_parallelism_threads=1
            )       
        )

    def fit(self, X, y):
        """ Fit the gaussian process based on observed data (X, y)

        Parameters
        ----------
        X : np nd.array. shape = (n_samples, n_dim)
            The design matrix
        y : np nd.array. shape = (n_samples, 1)
            The response variable
        """
        # Train length scales via gradient descent
        self.sess.run(tf.initialize_all_variables())
        # Perform in batches
        n_samples = X.shape[0]
        n_batches = n_samples/self.batch_size
        for i in xrange(self.n_epochs):
            # Shuffle the data
            shuffle = np.random.permutation(n_samples)
            X = X[shuffle]
            y = y[shuffle]
            for j in xrange(n_batches):
                # Get minibatch
                mini_X = X[j*self.batch_size : (j+1)*self.batch_size]
                mini_y = y[j*self.batch_size : (j+1)*self.batch_size]
                # Update 
                self.sess.run(self.train, feed_dict={self.X: mini_X,
                                                     self.y: mini_y})
        # Current hack: save the values
        self.K_invf = self.sess.run(self.K_inv, feed_dict={self.X: X, self.y: y})
        self.Xf = X
        self.yf = y
        
    def predict(self, X):
        """ Predict latent function evaluation and latent function variance at X

        Parameters
        ----------
        X : np or tf nd.array. shape = (n_samples, n_dim)
            The design matrix
        
        Returns
        -------
        y_pred : tf nd.array. shape = (n_samples, 1)
            The latent function mean evaluation
        var : tf nd.array. shape = (n_samples, 1)
            The latent function variance
        """
        # K(X, X*)
        K_ = self.kernel.covariance(X, self.Xf)
        # K(X, X*)[K(X, X) + sigma^2]^-1
        K_K_invf = tf.matmul(K_, self.K_invf)
        # Posterior mean
        y_pred = tf.matmul(K_K_invf, self.yf)
        # Posterior variance
        var = tf.reshape(
            tf.square(self.kernel.amp)
            - tf.reduce_sum(tf.mul(K_K_invf, K_), 1),
            [-1,1]
        )
        return y_pred, var

    
def main_1d():        
    import matplotlib.pyplot as plt
    # Create X and Y
    n_samples = 100
    new_samples = 400
    n_dim = 1
    X = np.float32(np.random.uniform(1, 10, [n_samples, n_dim]))
    y = np.float32((np.sin(X.sum(1)).reshape([n_samples, 1]) +
         np.random.normal(0,.1, [n_samples, 1])))
    kernel = SquaredExponential(n_dim=n_dim,
                                init_scale_range=(.1,.2),
                                init_amp=1.)
    gp = GaussianProcess(n_epochs=10,
                         batch_size=10,
                         n_dim=n_dim,
                         kernel=kernel,
                         noise=0.1,
                         train_noise=False,
                         optimizer=tf.train.GradientDescentOptimizer(0.01),
                         verbose=0)
    t0 = time.time()
    gp.fit(X, y)
    print "FitDuration: {0:.5f}".format(time.time() - t0)
    print gp.sess.run(gp.kernel.length_scales)
    X_new = np.float32(np.random.uniform(1, 10, [new_samples, n_dim]))
    X_new = np.sort(X_new, axis=0)
    y_pred, var = gp.predict(X_new)
    t1 = time.time()
    y_pred = gp.sess.run(y_pred)
    t2 = time.time()
    var = gp.sess.run(var)
    t3 = time.time()
    print "PredictionDuration: {0:.5f}".format(t2-t1)
    print "CovDuration: {0:.5f}".format(t3-t2)
    ci = np.sqrt(var)*2
    plt.plot(X_new, y_pred)
    plt.plot(X_new, y_pred+ci, 'g--')
    plt.plot(X_new, y_pred-ci, 'g--')
    plt.scatter(X, y)
    plt.show()
    
def main_2d():        
    from mpl_toolkits.mplot3d import Axes3D
    from matplotlib import cm
    from matplotlib.ticker import LinearLocator, FormatStrFormatter
    import matplotlib.pyplot as plt

    n_samples = 50
    n_dim = 2
    
    fig = plt.figure()
    ax = fig.gca(projection='3d')
    X = np.float32(np.random.uniform(0, 10, [n_samples, n_dim]))
    y = np.float32((np.sin(np.sqrt(X).sum(1)).reshape([n_samples, 1])
                    + np.random.normal(0, .1, [n_samples, 1])))
    scat = ax.scatter(X[:,0], X[:,1], y)

    kernel = SquaredExponential(n_dim=n_dim,
                                init_scale_range=(.1,.2),
                                init_amp=1.)
    gp = GaussianProcess(n_epochs=100,
                         batch_size=10,
                         n_dim=n_dim,
                         kernel=kernel,
                         noise=0.1,
                         train_noise=False,
                         optimizer=tf.train.GradientDescentOptimizer(0.001),
                         verbose=0)
    gp.fit(X, y)
    print gp.sess.run(gp.noise)
    print gp.sess.run(gp.kernel.length_scales)
    a = np.arange(0, 10, 0.25)
    b = np.arange(0, 10, 0.25)
    a, b = np.meshgrid(a, b)
    X_new = np.float32(np.hstack((a.ravel().reshape(-1, 1), b.ravel().reshape(-1, 1))))
    y_pred, cov = gp.predict(X_new)
    y_pred = (gp.sess.run(y_pred)).reshape(a.shape)
    var = gp.sess.run(cov)
    ci = (np.sqrt(var)*2).reshape(a.shape)
    surf = ax.plot_surface(a, b, y_pred, rstride=1, cstride=1, cmap=cm.coolwarm,
                           linewidth=0, antialiased=False, alpha=1)
    surf = ax.plot_surface(a, b, y_pred-ci, rstride=1, cstride=1, cmap=cm.cool,
                           linewidth=0, antialiased=False, alpha=.5)
    surf = ax.plot_surface(a, b, y_pred+ci, rstride=1, cstride=1, cmap=cm.cool,
                           linewidth=0, antialiased=False, alpha=.5)
    plt.show()

    
if __name__ == "__main__":
    main_2d()