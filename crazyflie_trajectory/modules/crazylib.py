"""This module contains all functions concerning the trajectories and motion planning
of the crzyflie."""

import numpy as np
import sys, os, json
from scipy.linalg import inv, cholesky
from scipy.signal import cont2discrete
import scipy.io
from math import sin, cos, sqrt
from math import sqrt
import random
import copy as copy
# -------------------------------------------------------------------------

def discrete_KF_update(x, u, z, A, B, C, P, Q, R):
    """
    Makes a discrete kalman update and returns the new state
    estimation and covariance matrix. Can handle empy control
    signals and empty B. Currently no warnings are issued if
    used improperly, which should be fixed in future iterations.
    if z is set to None, the update step is ignored and only prediction
    is used.

    N<=M and 0<K<=M are integers.
     
    :param x: State estimate at t = h*(k-1)
    :param u: If applicable, control signals at t = h*(k-1)
    :param z: Measurements at t = h*k.
    :type A: System matrix.
    :type B: Control signal matrix.
    :type C: Measurement matrix.
    :param P: Covariance at the previous update.
    :param Q: Estimated covariance matrix of state noise.
    :param R: Estimated covariance matrix of measurement noise.
    :type x: np.array of shape (M,1).
    :type u: np.array of shape (N,1), emty list or None. 
    :type z: np.array of shape (K,1).
    :type A: np.array of shape (M,M).
    :type B: np.array of shape (M,N), empty list or None.
    :type C: np.array of shape (K,M).
    :type P: np.array of shape (M,M).
    :type Q: np.array of shape (M,M).
    :type R: np.array of shape (K,K).
    
    
    :returns: xhat, Pnew
    :rtype: np.array (12,1), np.array (12,12)
    """
    # Kalman prediction
    if B == [] or u == []:
        xf = np.transpose(np.dot(A,x))
    else:
        xf = np.transpose(np.dot(A,x)) + np.transpose(np.dot(B,u))
    Pf = np.dot(np.dot(A,P),np.transpose(A)) + Q
    
    # Kalman update
    if z is not None:
        Knum =  np.dot(Pf,np.transpose(C))
        Kden = np.dot(C,np.dot(Pf,np.transpose(C))) + R
        K = np.dot(Knum,inv(Kden))
        xhat = xf + np.dot(K, (z - np.dot(C,xf)))
        Pnew = np.dot((np.eye(Q.shape[0]) - np.dot(K,C)), Pf)
    else:
        xhat = xf
        Pnew = Pf
    return xhat, Pnew

# -------------------------------------------------------------------------

def discrete_AKF_update(x, u, z, zhist, A, B, C, P, Q, R, trajectory, t, Ts):
    """
    Makes an asynchronous kalman update and returns the new state
    estimation and covariance matrix. Can handle emtpy control
    signals and empty B. Currently no warnings are issued if
    used improperly, which should be fixed in future iterations.
    This function is very adapted to the problem at hand and should
    not be used outside of the kinect node.

    N<=M and 0<K<=M are integers.

    :param x: State estimate at t = h*(k-1)
    :param u: If applicable, control signals at t = h*(k-1)
    :param z: Measurements at t = h*k.
    :type zhist: Solution history of the measurements dating back X timesteps.
    :type A: System matrix.
    :type B: Control signal matrix.
    :type C: Measurement matrix.
    :param P: Covariance at the previous update.
    :param Q: Estimated covariance matrix of state noise.
    :param R: Estimated covariance matrix of measurement noise.
    :param trajectory: Intended acceleration trajectory.
    :param t: The current time.
    :param Ts: The timestep at which the new data is generated by openni.
    :type x: np.array of shape (M,1).
    :type u: np.array of shape (N,1), emty list or None. 
    :type z: np.array of shape (K,1).
    :type zhist: np.array of shape (1,X).
    :type A: np.array of shape (M,M).
    :type B: np.array of shape (M,N), empty list or None.
    :type C: np.array of shape (K,M).
    :type P: np.array of shape (M,M).
    :type Q: np.array of shape (M,M).
    :type R: np.array of shape (K,K).
    :type trajectory: Vectorvalued function handle.
    :type t: float.
    :type Ts: float.
    
    :returns: xhat, Pnew
    :rtype: np.array (12,1), np.array (12,12)
    """
    
    # Updates zhistory vector
    zhist[0:-1] = zhist[1:]
    zhist[-1] = z
    
    # Updates the covariance with the most recent synchronized measurement
    if np.isnan(zhist[0][0]):
        xhat = x
        xpred = x
    else:
        xhat, P = discrete_KF_update(x, u, zhist[-1], A, B, C, P, Q, R)
    
        # Predics what the future state will look like based on current data
        xpred = xhat
        Ppred = P
        for ii in range(len(zhist)-1):
            zpred = zhist[ii+1]
            zpred[1] = trajectory(t + (1 + ii - len(zhist))*Ts) + np.dot(np.random.randn(1),R[1,1])[0]
            xpred, Ppred = discrete_KF_update(xpred, u, zhist[ii+1], A, B, C, Ppred, Q, R)

    return xhat, xpred, P, zhist

# -------------------------------------------------------------------------

def discrete_UKF_update(x, u, z, F, H, param, P, Q, R):
    """
    Makes a companion unscented kalman update and returns the new state
    estimation and covariance matrix. Currently no warnings are issued if
    used improperly, which should be fixed in future iterations.
    This is a very general implementation, with the limitation that noise
    is assumed to be zero mean. The current parameters should be outsourced
    to param, and are currently set to yeld good result for white gaussian
    noise.

    :param x: State estimate at t = h*(k-1)
    :param u: If applicable, control signals at t = h*(k-1)
    :param z: Measurements at t = h*k.
    :param F: Nonlinear state equations in discrete time. Returns an (M,1)
        numpy array as the first arg.
    :param G: Nonlinear measurement equations in discrete time. Returns an
        (K,1) numpy array as the first arg.
    :param param: Parameter dictionary with quadcopter coefficients.
    :param P: Covariance at the previous update.
    :param Q: Estimated covariance matrix of state noise.
    :param R: Estimated covariance matrix of measurement noise.
    :type x: np.array of shape (M,1)
    :type u: np.array of shape (N,1), emty list or None. 
    :type z: np.array of shape (K,1)
    :type F: function handle of type F(x,u,param).
    :type G: function handle of type H(x,param).
    :type param: Dictionary
    :type P: np.array of shape (M,M).
    :type Q: np.array of shape (M,M).
    :type R: np.array of shape (K,K).

    :returns: xhat, Pnew
    :rtype: np.array (12,1), np.array (12,12)
    """

    # ~~~ UKF Parameters ~~~
    L = x.shape[0]                      # Number of discrete states
    Nu = u.shape[0]                     # Number of control signals
    Nz = z.shape[0]                     # Number of measurement signals
    beta = 2                            # Optimal for gaussian distributions
    alpha = 5e-1                        # Tuning parameter (0 < alpha < 1e-4)
    keta = 0;                           # Tuning parameter (set to 0 or 3-L)
    lam =  alpha ** 2 * (L + keta) - L; # Scaling factor (see E. Wan for details)
    
    # ~~~ UKF Weights ~~~
    # Weight for mean
    Wm0 = np.array([lam/(L + lam)])
    Wmi = (1/(2 * (L + lam)))*np.ones((1,2*L))[0]
    Wm = np.append(Wm0,Wmi)
    
    # Weight for covariances
    Wc0 = np.array([lam/(L + lam)+(1 - alpha ** 2 + beta)] )
    Wci = (1/(2 * (L + lam)))*np.ones((1,2*L))[0]
    Wc = np.append(Wc0,Wci)

    # ~~~ Computes covariances and sigma points (predictive step) ~~~
    Psqrt = sqrt(L + lam) * np.transpose(cholesky(P));
    X = np.hstack((x, np.tile(x,(1,L))+Psqrt, np.tile(x,(1,L))-Psqrt))
    
    Xf = np.zeros(X.shape)
    for ii in range(2*L+1): 
        Xf[:,[ii]], _ = F(X[:,[ii]], u, param)

    # ~~~ UT-transform of the dynamics (time update) ~~~
    xMean = np.zeros((L,1))
    for ii in range(2*L+1):
        xMean += Wm[ii]*Xf[:,[ii]]        # Transformed mean (x)
    xDev = Xf - np.tile(xMean,(1,2*L+1))  # Transformed deviations (x)
   
    # ~~~ UT-transform of the measurements (measurement update) ~~~
    Yf = np.zeros((Nz,2*L+1))
    for ii in range(2*L+1): 
        Yf[:,[ii]] = H(Xf[:,[ii]])
        
    yMean = np.zeros((Nz,1))
    for ii in range(2*L+1): 
        yMean += Wm[ii]*Yf[:,[ii]]        # Transformed mean (y)
    yDev = Yf - np.tile(yMean,(1,2*L+1))  # Transformed deviations (y)
    
    # ~~~ Compute transformed covariance matrices ~~~
    Pxx = np.dot(np.dot(xDev,np.diag(Wc)),np.transpose(xDev)) + Q # transformed state covariance
    Pxy = np.dot(np.dot(xDev,np.diag(Wc)),np.transpose(yDev))     # transformed cross covariance
    Pyy = np.dot(np.dot(yDev,np.diag(Wc)),np.transpose(yDev)) + R # transformed measurement covariance
    
    # ~~~ Correction update ~~~
    K = np.dot(Pxy, inv(Pyy))
    xhat = xMean + np.dot(K, z - yMean)             # State correction
    P = Pxx - np.dot(np.dot(K,Pyy),np.transpose(K)) # Covariance correction
    return xhat, P

# -----------------------------------------------------------------------------

def quadcopter_dynamics(x, u, param):
    """The Tait-Bryan model of the quadcopter which is used in non-linear
    state estimation on the host and for simulation purposes. The state is
    updated internally and updated on every time step with reference to the
    input control signal omega. The parameters defining the process and states
    are loaded from a parameter dictionary on the same for as that used in the
    configuration file (see /config/).
    
    :param x: State vector x = [p, dp, eta, deta]^T at a time k. 
    :param u: Control signals on the form [T, tau_x, tau_y, tau_z]^T at a time k.
    :param param: Parameter dictionary with quadcopter coefficients.
    :type x: np.array of shape (12,1)
    :type u: np.array of shape (4,1)
    :type param: Dictionary

    :returns: xout, yout
    :rtype: np.array (12,1), np.array (M,1) as specified in C
    """

    # Extract angles and parameters
    phi, theta, psi, phidot, thetadot, psidot = np.reshape(x[6:12,0:1],[1,6])[0]
    Ts = param['global']['inner_loop_h']
    g = param['quadcopter_model']['g']
    m = param['quadcopter_model']['m']
    k = param['quadcopter_model']['k']
    A = param['quadcopter_model']['A']
    I = param['quadcopter_model']['I']
    l = param['quadcopter_model']['l']
    b = param['quadcopter_model']['b']
    
    u = u[:,0]
    T = k * sum(u ** 2)

    Ixx, Iyy, Izz = I
    
    Sphi = sin(phi)
    Stheta = sin(theta)
    Spsi = sin(psi);
    Cphi = cos(phi)
    Ctheta = cos(theta)
    Cpsi = cos(psi)
    
    C11 = 0.
    C12 = ((Iyy - Izz) * (thetadot * Cphi * Sphi +
           psidot * Sphi ** 2 *Ctheta) +
           (Izz - Iyy) * psidot * Cphi ** 2 *Ctheta -
           Ixx * psidot * Ctheta)
    C13 = (Izz - Iyy) * psidot * Cphi * Sphi * Ctheta ** 2
    C21 = ((Izz - Iyy) * (thetadot * Cphi * Sphi +
           psidot * Sphi * Ctheta) +
           (Iyy - Izz) * psidot * Cphi ** 2 * Ctheta -
           Ixx * psidot * Ctheta)
    C22 = (Izz - Iyy) * phidot * Cphi * Sphi
    C23 = (-Ixx * psidot * Stheta * Ctheta +
           Iyy * psidot * Sphi ** 2 * Stheta * Ctheta +
           Izz * psidot * Cphi ** 2 * Stheta * Ctheta)
    C31 = ((Iyy - Izz) * psidot * Ctheta ** 2 * Sphi * Cphi -
           Ixx * thetadot * Ctheta)
    C32 = ((Izz - Iyy) * (thetadot * Cphi * Sphi * Stheta +
           phidot * Sphi ** 2 * Ctheta) +
           (Iyy - Izz) * phidot * Cphi ** 2 * Ctheta +
           Ixx * psidot * Stheta * Ctheta -
           Iyy * psidot * Sphi ** 2 * Stheta * Ctheta -
           Izz * psi * Cphi ** 2 * Stheta * Ctheta)
    C33 = ((Iyy - Izz) * phidot * Cphi * Sphi * Ctheta ** 2 -
           Iyy * thetadot * Sphi ** 2 * Ctheta * Stheta -
           Izz * thetadot * Cphi ** 2 * Ctheta * Stheta +
           Ixx * thetadot * Ctheta * Stheta)
    
    C = np.array([[C11,C12,C13],
                  [C21,C22,C23],
                  [C31,C32,C33]]);   
    
    tau_phi =  l * k * (-u[1] ** 2 + u[3] ** 2)
    tau_theta =  l * k * (-u[0] ** 2 + u[2] ** 2)
    tau_psi =  b * (u[0] ** 2 - u[1] ** 2 +
                    u[2] ** 2 - u[3] ** 2)
    
    tau_b = np.array([[tau_phi],[tau_theta],[tau_psi]])
    
    J11 = Ixx
    J12 = 0.
    J13 = -Ixx*Stheta
    J21 = 0.
    J22 = Iyy * Cphi ** 2 + Izz * Sphi ** 2
    J23 = (Iyy - Izz) * Cphi * Sphi * Ctheta
    J31 = -Ixx * Stheta
    J32 = (Iyy - Izz) * Cphi * Sphi * Ctheta
    J33 = (Ixx * Stheta ** 2 + Iyy * Sphi ** 2 * Ctheta ** 2 +
           Izz * Cphi ** 2 * Ctheta ** 2)
    J = np.array([[J11,J12,J13],
                  [J21,J22,J23],
                  [J31,J32,J33]])
    
    invJ = inv(J)

    I3 = np.diag(np.ones([1,3])[0])
    
    Ac = np.zeros([12,12])
    Ac[0:3,3:6] = I3
    Ac[3:6,3:6] = -(1/m)*np.diag(A)
    Ac[6:9,9:12] = I3
    Ac[9:12,9:12] = -np.dot(invJ,C)
    
    Rz = (1/m) * np.array([[cos(psi) * sin(theta) * cos(phi) + sin(psi) * sin(phi)],
                           [sin(psi) * sin(theta) * cos(phi) - cos(psi) * sin(phi)],
                           [cos(theta) * cos(phi)]])
    
    Bc = np.zeros([12,4])
    Bc[3:6,0:1] = Rz
    Bc[9:12,1:4] = invJ
    
    Cc = np.zeros([7,12])
    Cc[0:7,2:9] = np.diag(np.ones([1,7])[0])
    
    Dc = np.array([])
    
    discreteSystem = cont2discrete((Ac,Bc,Cc,Dc), Ts, method='zoh', alpha=None)
    
    Ad = discreteSystem[0]
    Bd = discreteSystem[1]
    Cd = discreteSystem[2]

    G = np.zeros([12,1])
    G[5,0]=-g
    
    # Sets up control signal
    u = np.concatenate([[[T]],tau_b])
    
    xout = np.dot(Ad,x) + np.dot(Bd,u) + G*Ts
    yout = np.dot(Cd,x)
    return xout, yout
        
# -----------------------------------------------------------------------------

def print_progress (iteration, total, prefix = '', suffix = '', decimals = 2, barLength = 30):
    """Prints progress bar in terminal window
    
    :param iteration: The current iteration.
    :param total: The total number of iterations before completion.
    :param prefix: Empty by default, specifies text before the progress bar.
    :param suffix: Empty by default, specifies text after the progress bar.
    :param decimals: Number of decimals in the percentage calculation.
    :param barLength: The progress bar length.
    :type iteration: int
    :type total: - int
    :type prefix: - string
    :type suffix: - string
    :type decimals: - int
    :type barLength: - int
    """
    filledLength = int(round(barLength * iteration / float(total)))
    percents = round(100.00 * (iteration / float(total)), decimals)
    bar = '#' * filledLength + '-' * (barLength - filledLength)
    sys.stdout.write('%s [%s] %s%s %s\r' % (prefix, bar, percents, '%', suffix)),
    sys.stdout.flush()
    if iteration == total:
        print("\n")

# -----------------------------------------------------------------------------
