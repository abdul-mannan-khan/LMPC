import numpy as np
import pdb
import scipy as sp
import cvxpy as cp
import itertools, sys

class FTOCP(object):
	""" Finite Time Optimal Control Problem (FTOCP)
	Methods:
		- solve: solves the FTOCP given the initial condition x0, terminal contraints (optinal) and terminal cost (optional)
		- model: given x_t and u_t computes x_{t+1} = Ax_t + Bu_t

	"""
	def __init__(self, N, A, B, Q, R, Hx=None, gx=None, Hu=None, gu=None):
		# Define variables
		self.N = N # Horizon Length

		# System Dynamics (x_{k+1} = A x_k + Bu_k)
		self.A = A
		self.B = B
		self.n = A.shape[1]
		self.d = B.shape[1]

		# Linear state constraints (Hx*x <= gx)
		self.Hx = Hx
		self.gx = gx

		# Linear input constraints (Hu*u <= gu)
		self.Hu = Hu
		self.gu = gu

		# Cost (h(x,u) = x^TQx +u^TRu)
		self.Q = Q
		self.R = R

	# def stage_cost_fun(self, x, xf, u):
	# 	# Using the cvxpy norm function here
	# 	return cp.norm(self.Q**0.5*(x-xf))**2 + cp.norm(self.R**0.5*u)**2
	#
	# def term_cost_fun(self, x, xf):
	# 	# Using the cvxpy norm function here
	# 	return cp.norm(self.Q**0.5*(x-xf))**2

	def solve(self, x0, xf=None, abs_t=None, deltas=None, SS=None, Qfun=None, CVX=False, verbose=False):
		"""This methos solve a FTOCP given:
			- x0: initial condition
			- xf: (optional) goal condition, defaults to the origin
			- abs_t: (required if deltas is provided) absolute time step
			- deltas: (optional) allowed deviations from previous trajectory
			- SS: (optional) contains a set of state and the terminal constraint is ConvHull(SS)
			- Qfun: (optional) cost associtated with the state stored in SS. Terminal cost is BarycentrcInterpolation(SS, Qfun)
			- CVX: (optional)
		"""
		if xf is None:
			xf = np.zeros(self.n)
		else:
			xf = np.reshape(xf, self.n)

		# Initialize Variables
		x = cp.Variable((self.n, self.N+1))
		u = cp.Variable((self.d, self.N))

		# If SS is given construct a matrix collacting all states and a vector collection all costs
		if SS is not None:
			# SS_vector = np.squeeze(list(itertools.chain.from_iterable(SS))).T # From a 3D list to a 2D array
			# SS_vector = np.hstack(SS)
			SS_vector = SS[-1] # Only use last trajectory
			# Qfun_vector = np.expand_dims(np.array(list(itertools.chain.from_iterable(Qfun))), 0) # From a 2D list to a 1D array
			Qfun_vector = np.array(Qfun[-1])
			if CVX:
				lambVar = cp.Variable((SS_vector.shape[1], 1), boolean=False) # Initialize vector of variables
			else:
				lambVar = cp.Variable((SS_vector.shape[1], 1), boolean=True) # Initialize vector of variables
				gamVar = cp.Variable((self.N+1), boolean=True)

		if not CVX:
			M = 1000 # Big M multiplier

		constr = [x[:,0] == x0] # Initial condition
		for i in range(self.N):
			constr += [x[:,i+1] == self.A*x[:,i] + self.B*u[:,i]] # Dynamics

			if self.Hx is not None:
				constr += [self.Hx*x[:,i] <= self.gx] # State constraints
			if self.Hu is not None:
				constr += [self.Hu*u[:,i] <= self.gu] # Input constraints

			if not CVX:
				# Big M reformulation of minimum time objective: \gamma = 1 when x has not reached x_f, \gamma = 0 when x has reached x_f
				bigM_ub = xf+M*np.ones(self.n)*gamVar[i]
				bigM_lb = xf-M*np.ones(self.n)*gamVar[i]
				constr += [x[:,i] <= bigM_ub, -x[:,i] <= -bigM_lb]
			if deltas is not None:
				# Constrain positions to be within mutual agreed deviations at each time step
				if abs_t is None:
					raise(ValueError('Absolute time step must be given'))
				t = min(abs_t+i, SS_vector.shape[1]-1)
				# constr += [cp.norm_inf(x[:2,i]-SS_vector[:2,t]) <= deltas[t]]
				constr += [cp.quad_form(x[:2,i]-SS_vector[:2,t], np.eye(2)) <= deltas[t]**2]

		# Terminal Constraint if SS not empty
		if SS is not None:
			# Terminal state \in ConvHull(SS) or if \lambda is boolean, then terminal state is one of the points in the SS
			constr += [SS_vector * lambVar[:,0] == x[:,self.N],
						np.ones((1, SS_vector.shape[1])) * lambVar[:,0] == 1, # \lambda sum to 1 or only 1 \lambda is equal to 1
						lambVar >= 0] # Multipliers are positive definite
			if not CVX:
				bigM_ub = xf+M*np.ones(self.n)*gamVar[self.N]
				bigM_lb = xf-M*np.ones(self.n)*gamVar[self.N]
				constr += [x[:,self.N] <= bigM_ub, -x[:,self.N] <= -bigM_lb]
			if deltas is not None:
				# Constrain last position to be within mutual agreed deviations
				t = min(abs_t+self.N, SS_vector.shape[1]-1)
				# constr += [cp.norm_inf(x[:2,self.N]-SS_vector[:2,t]) <= deltas[t]]
				# constr += [cp.norm(x[:2,self.N]-SS_vector[:2,t], p=2)**2 <= deltas[t]**2]
				constr += [cp.quad_form(x[:2,self.N]-SS_vector[:2,t], np.eye(2)) <= deltas[t]**2]

		# Cost Function
		cost = 0
		for i in range(self.N):
			if SS is not None:
				cost += 10*x[1,i]**2 + cp.quad_form(u[:,i], self.R)
			else:
				cost += cp.quad_form(x[:,i]-xf, self.Q) + cp.quad_form(u[:,i], self.R) # Running cost h(x,u) = x^TQx + u^TRu
			if not CVX:
				cost += gamVar[i]

		# Terminal cost if SS not empty
		if SS is not None:
			cost += Qfun_vector * lambVar[:,0]  # It terminal cost is given by interpolation using \lambda
		else:
			cost += cp.quad_form(x[:,self.N]-xf, self.Q)
		# if not CVX:
		# 	cost += gamVar[self.N]

		# Solve the Finite Time Optimal Control Problem
		problem = cp.Problem(cp.Minimize(cost), constr)
		problem.solve(verbose=verbose)

		if problem.status == 'infeasible':
			raise(ValueError('Optimization was infeasible for step %i' % abs_t))
		elif problem.status == 'unbounded':
			raise(ValueError('Optimization was unbounded for step %i' % abs_t))

		return(x.value, u.value)

	def model(self, x, u):
		# Compute state evolution
		return self.A.dot(x) + self.B.dot(u)

	def update_model(self, A=None, B=None):
		if A is not None:
			self.A = A
		if B is not None:
			self.B = B

	def update_cost(self, Q=None, R=None):
		if Q is not None:
			self.Q = Q
		if R is not None:
			self.R = R

	def update_constraints(self, Hx=None, gx=None, Hu=None, gu=None):
		if Hx is not None and gx is not None:
			self.Hx = Hx
			self.gx = gx
		if Hu is not None and gu is not None:
			self.Hu = Hu
			self.gu = gu
