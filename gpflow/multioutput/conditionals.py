# Copyright 2018 GPflow authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import tensorflow as tf

from .. import settings
from ..decors import name_scope
from ..dispatch import conditional
from ..features import InducingPoints, InducingFeature
from ..kernels import Kernel, Combination
from ..probability_distributions import Gaussian
from ..conditionals import base_conditional, expand_independent_outputs

from .kernels import Kuf, Kuu
from .features import Mof, SeparateIndependentMof, SharedIndependentMof, MixedKernelSharedMof
from .kernels import Mok, SharedIndependentMok, SeparateIndependentMok, SeparateMixedMok

# TODO: Make all output shapes of conditionals equal: dependent on full_cov and full_cov_output
# TODO: Add tensorflow assertions of shapes
# TODO: extract duplicate code (if possible)


@conditional.register(object, SharedIndependentMof, SharedIndependentMok, object)
@name_scope()
def _conditional(Xnew, feat, kern, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    """
    Kmm = Kuu(feat, kern, jitter=settings.numerics.jitter_level)  # M x M
    Kmn = Kuf(feat, kern, Xnew)  # M x N
    if full_cov:
        Knn = kern.K(Xnew, full_cov_output=False)[..., 0]  # N x N
    else:
        Knn = kern.Kdiag(Xnew, full_cov_output=False)[..., 0]  # N
    fmean, fvar = base_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, q_sqrt=q_sqrt, white=white)  # N x P,  N x (x N) x P
    return fmean, expand_independent_outputs(fvar, full_cov, full_cov_output)


@conditional.register(object, SeparateIndependentMof, SeparateIndependentMok, object)
@conditional.register(object, SharedIndependentMof, SeparateIndependentMok, object)
@conditional.register(object, SeparateIndependentMof, SharedIndependentMok, object)
@name_scope()
def _conditional(Xnew, feat, kern, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    Multi-output GP with independent GP priors.
    Number of latent processes equals the number of outputs (L = P). Expected kernels:
     Kmm
    :param f: M x P
    :param q_sqrt: M x P  or  P x M x M
    :return: N x P ,
    """
    print("Conditional")
    print("object, SharedIndependentMof, SeparateIndependentMok, object")
    print("object, SeparateIndependentMof, SharedIndependentMok, object")
    print("object, SeparateIndependentMof, SeparateIndependentMok, object")
    # Following are: P x M x M  -  P x M x N  -  P x N(x N)
    Kmms = Kuu(feat, kern, jitter=settings.numerics.jitter_level)  # P x M x M
    Kmns = Kuf(feat, kern, Xnew)  # P x M x N
    # TODO(VD) is this still necessary
    kern_list = kern.kern_list if isinstance(kern, Combination) else [kern.kern] * len(feat.feat_list)
    Knns = tf.stack([k.K(Xnew) if full_cov else k.Kdiag(Xnew) for k in kern_list], axis=0)
    fs = tf.transpose(f)[:, :, None]  # P x M x 1
    # P x 1 x M x M  or  P x M x 1
    q_sqrts = tf.transpose(q_sqrt)[:, :, None] if q_sqrt.shape.ndims == 2 else q_sqrt[:, None, :, :]

    def single_gp_conditional(t):
        Kmm, Kmn, Knn, f, q_sqrt = t
        return base_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, q_sqrt=q_sqrt, white=white)

    rmu, rvar = tf.map_fn(single_gp_conditional,
                          (Kmms, Kmns, Knns, fs, q_sqrts),
                          (settings.float_type, settings.float_type))  # P x N x 1  ,  P x N(x N) x 1

    fmu = tf.matrix_transpose(rmu[..., 0])
    fvar = rvar[..., 0]

    if full_cov_output and full_cov:
        fvar = tf.diag(tf.transpose(fvar, [1, 2, 0]))
        fvar = tf.transpose(fvar, [0, 2, 1, 3])  # N x P x N x P
    elif not full_cov_output and full_cov:
        pass  # P x N x N
    elif full_cov_output and not full_cov:
        fvar = tf.diag(tf.matrix_transpose(fvar))  # N x P x P
    elif not full_cov_output and not full_cov:
        fvar = tf.matrix_transpose(fvar)  # N x P

    return fmu, fvar

@conditional.register(object, (SharedIndependentMof, SeparateIndependentMof), SeparateMixedMok, object)
@name_scope()
def _conditional(Xnew, feat, kern, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    Multi-output GP with independent GP priors
    :param Xnew:
    :param feat:
    :param kern:
    :param f: M x L
    :param full_cov:
    :param full_cov_output:
    :param q_sqrt: L x M  or L x M x M
    :param white:
    :return:
    """
    Kmm = Kuu(feat, kern, jitter=settings.numerics.jitter_level)  # L x M x M
    Kmn = Kuf(feat, kern, Xnew)  # M x L x N x P
    Knn = kern.K(Xnew, full_cov_output=full_cov_output) if full_cov \
        else kern.Kdiag(Xnew, full_cov_output=full_cov_output)  # N x P(x N)x P  or  N x P(x P)

    return independent_interdomain_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, full_cov_output=full_cov_output,
                                           q_sqrt=q_sqrt, white=white)


@conditional.register(object, InducingPoints, Mok, object)
@name_scope()
def _conditional(Xnew, feat, kern, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    Multi-output GP with fully correlated inducing variables.
    The inducing variables are shaped in the same way as evaluations of K, to allow a default
    inducing point scheme for multi-output kernels.

     Kmm : M x L x M x P
     Kmn : M x L x N x P

    :param f: ML x 1
    :param q_sqrt: ML x 1  or  1 x ML x ML
    """
    Kmm = Kuu(feat, kern, jitter=settings.numerics.jitter_level)  # M x L x M x P
    Kmn = Kuf(feat, kern, Xnew)  # M x L x N x P
    Knn = kern.K(Xnew, full_cov_output=full_cov_output) if full_cov \
        else kern.Kdiag(Xnew, full_cov_output=full_cov_output)  # N x P(x N)x P  or  N x P(x P)

    M, L, N, K = [tf.shape(Kmn)[i] for i in range(Kmn.shape.ndims)]
    Kmm = tf.reshape(Kmm, (M * L, M * L))

    if full_cov == full_cov_output:
        Kmn = tf.reshape(Kmn, (M * L, N * K))
        Knn = tf.reshape(Knn, (N * K, N * K)) if full_cov else tf.reshape(Knn, (N * K,))
        fmean, fvar = base_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, q_sqrt=q_sqrt, white=white)  # NK, NK(x NK)
        fmean = tf.reshape(fmean, (N, K))
        fvar = tf.reshape(fvar, (N, K, N, K) if full_cov else (N, K))
    else:
        Kmn = tf.reshape(Kmn, (M * L, N, K))
        fmean, fvar = fully_correlated_conditional(Kmn, Kmm, Knn, f, full_cov=full_cov, full_cov_output=full_cov_output,
                                                   q_sqrt=q_sqrt, white=white)
        # TODO: Fix this output shape
    fmean = tf.Print(fmean, [tf.shape(fmean), tf.shape(fvar)], summarize=100)
    return fmean, fvar


@conditional.register(object, MixedKernelSharedMof, SeparateMixedMok, object)
@name_scope()
def _conditional(Xnew, feat, kern, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    """
    print("conditional: MixedKernelSharedMof, SeparateMixedMok")
    independent_cond = conditional.dispatch(object, SeparateIndependentMof, SeparateIndependentMok, object)
    gmu, gvar = independent_cond(Xnew, feat, kern, f, full_cov=full_cov, q_sqrt=q_sqrt,
                                 full_cov_output=False, white=white)  # N x L, L x N x N or N x L

    gmu = tf.matrix_transpose(gmu)  # L x N
    if not full_cov:
        gvar = tf.matrix_transpose(gvar)  # L x N (x N)

    Wgmu = tf.tensordot(gmu, kern.W, [[0], [1]])  # N x P

    if full_cov_output:
        Wt_expanded = tf.matrix_transpose(kern.W)[:, None, :]  # L x 1 x P
        if full_cov:
            Wt_expanded = tf.expand_dims(Wt_expanded, axis=-1)  # L x 1 x P x 1

        gvarW = tf.expand_dims(gvar, axis=2) * Wt_expanded  # L x N x P (x N)
        WgvarW = tf.tensordot(gvarW, kern.W, [[0], [1]])  # N x P (x N) x P
    else:
        if not full_cov:
            WgvarW = tf.tensordot(gvar, kern.W**2, [[0], [1]])  # N x P
        else:
            WgvarW = tf.tensordot(kern.W**2, gvar, [[1], [0]])  # P x N (x N)

    return Wgmu, WgvarW


# ========================= Conditional Implementations ========================
# =========================.............................========================


def independent_interdomain_conditional(Kmn, Kmm, Knn, f, *, full_cov=False, full_cov_output=False, 
                                        q_sqrt=None, white=False):
    """
    The inducing outputs u live in the g-space (R^L), 
    therefore Kuf (Kmn) is an interdomain covariance matrix.

    :param Kmn: M x L x N x P
    :param Kmm: L x M x M
    :param Knn: N x P  or  N x N  or  P x N x N  or  N x P x N x P
    :param f: data matrix, M x L
    :param q_sqrt: L x M x M  or  M x L
    :return: N x P  ,  N x R x P x P
    """
    print("independent_interdomain_conditional")
    # TODO: Allow broadcasting over L if priors are shared?
    # TODO: Change Kmn to be L x M x N x P? Saves a transpose...
    M, L, N, P = [tf.shape(Kmn)[i] for i in range(Kmn.shape.ndims)]

    Lm = tf.cholesky(Kmm)  # L x M x M

    # Compute the projection matrix A
    Kmn = tf.reshape(tf.transpose(Kmn, (1, 0, 2, 3)), (L, M, N * P))
    A = tf.matrix_triangular_solve(Lm, Kmn, lower=True)  # L x M x M  *  L x M x NP  ->  L x M x NP
    Ar = tf.reshape(A, (L, M, N, P))

    # compute the covariance due to the conditioning
    if full_cov and full_cov_output:
        fvar = Knn - tf.tensordot(Ar, Ar, [[0, 1], [0, 1]])  # N x P x N x P
    elif full_cov and not full_cov_output:
        At = tf.reshape(tf.transpose(Ar), (P, N, M * L))  # P x N x ML
        fvar = Knn - tf.matmul(At, At, transpose_b=True)  # P x N x N
    elif not full_cov and full_cov_output:
        At = tf.reshape(tf.transpose(Ar, [2, 3, 1, 0]), (N, P, M * L))  # N x P x ML
        fvar = Knn - tf.matmul(At, At, transpose_b=True)  # N x P x P
    elif not full_cov and not full_cov_output:
        fvar = Knn - tf.reshape(tf.reduce_sum(tf.square(A), [0, 1]), (N, P))  # Knn: N x P

    # another backsubstitution in the unwhitened case
    if not white:
        A = tf.matrix_triangular_solve(Lm, Ar)  # L x M x M  *  L x M x NP  ->  L x M x NP
        Ar = tf.reshape(A, (L, M, N, P))

    fmean = tf.tensordot(Ar, f, [[0, 1], [0, 1]])  # N x P

    if q_sqrt is not None:
        Lf = tf.matrix_band_part(q_sqrt, -1, 0)  # L x M x M
        if q_sqrt.shape.ndims == 3:
            LTA = tf.matmul(Lf, A, transpose_a=True)  # L x M x M  *  L x M x NP  ->  L x M x NP
        else:
            raise NotImplementedError()

        if full_cov and full_cov_output:
            LTAr = tf.reshape(LTA, (L * M, N * P))
            fvar = fvar + tf.reshape(tf.matmul(LTAr, LTAr, transpose_a=True), (N, P, N, P))
        elif full_cov and not full_cov_output:
            LTAr = tf.transpose(tf.reshape(LTA, (L * M, N, P)), [0, 3, 1, 2])  # P x LM x N
            fvar = fvar + tf.matmul(LTAr, LTAr, transpose_a=True)  # P x N x N
        elif not full_cov and full_cov_output:
            LTAr = tf.transpose(tf.reshape(LTA, (L * M, N, P)), [1, 0, 2])  # N x LM x P
            fvar = fvar + tf.matmul(LTAr, LTAr, transpose_a=True)  # N x P x P
        elif not full_cov and not full_cov_output:
            fvar = fvar + tf.reshape(tf.reduce_sum(tf.square(LTA), (0, 1)), (N, P))
    return fmean, fvar


def fully_correlated_conditional(Kmn, Kmm, Knn, f, *, full_cov=False, full_cov_output=False, q_sqrt=None, white=False):
    """
    This function handles conditioning of multi-output GPs in the case where the conditioning
    points are all fully correlated, in both the prior and posterior.
    :param Kmn: M x N x K
    :param Kmm: M x M
    :param Knn: N x K  or  N x N  or  K x N x N  or  N x K x N x K
    :param f: data matrix, M x R
    :param q_sqrt: R x M x M  or  R x M
    :return: N x R x K  ,  N x R x K x K
    """
    print("fully correlated conditional")
    R = tf.shape(f)[1]
    M, N, K = [tf.shape(Kmn)[i] for i in range(Kmn.shape.ndims)]
    Lm = tf.cholesky(Kmm)

    # Compute the projection matrix A
    # Lm: M x M    Kmn: M x NK
    Kmn = tf.reshape(Kmn, (M, N * K))  # M x NK
    A = tf.matrix_triangular_solve(Lm, Kmn, lower=True)  # M x NK
    Ar = tf.reshape(A, (M, N, K))

    # compute the covariance due to the conditioning
    if full_cov and full_cov_output:
        # fvar = Knn - tf.matmul(Ar, Ar, transpose_a=True)  # NK x NK, then reshape?
        fvar = Knn - tf.tensordot(Ar, Ar, [[0], [0]])  # N x K x N x K
    elif full_cov and not full_cov_output:
        At = tf.transpose(Ar)  # K x N x M
        fvar = Knn - tf.matmul(At, At, transpose_b=True)  # K x N x N
    elif not full_cov and full_cov_output:
        # This transpose is annoying
        At = tf.transpose(Ar, [1, 0, 2])  # N x M x K
        # fvar = Knn - tf.einsum('mnk,mnl->nkl', Ar, Ar)
        fvar = Knn - tf.matmul(At, At, transpose_a=True)  # N x K x K
    elif not full_cov and not full_cov_output:
        # Knn: N x K
        fvar = Knn - tf.reshape(tf.reduce_sum(tf.square(A), [0, 1]), (N, K))  # Can also do this with a matmul

    # another backsubstitution in the unwhitened case
    if not white:
        A = tf.matrix_triangular_solve(tf.matrix_transpose(Lm), A, lower=False)  # M x NK
        raise NotImplementedError("Need to verify this.")

    # f: M x R
    fmean = tf.matmul(f, A, transpose_a=True)  # R x M  *  M x NK  ->  R x NK
    fmean = tf.reshape(fmean, (R, N, K))

    if q_sqrt is not None:
        Lf = tf.matrix_band_part(q_sqrt, -1, 0)  # R x M x M
        if q_sqrt.get_shape().ndims == 3:
            A_tiled = tf.tile(A[None, :, :], tf.stack([R, 1, 1]))  # R x M x NK
            LTA = tf.matmul(Lf, A_tiled, transpose_a=True)  # R x M x NK
        elif q_sqrt.get_shape().ndims == 2:
            raise NotImplementedError("Does not support diagonal q_sqrt yet...")
        else:  # pragma: no cover
            raise ValueError("Bad dimension for q_sqrt: %s" %
                             str(q_sqrt.get_shape().ndims))

        if full_cov and full_cov_output:
            addvar = tf.matmul(LTA, LTA, transpose_a=True)  # R x NK x NK
            fvar = fvar[None, :, :, :, :] + tf.reshape(addvar, (R, N, K, N, K))
        elif full_cov and not full_cov_output:
            raise NotImplementedError()
        elif not full_cov and full_cov_output:
            LTAr = tf.transpose(tf.reshape(LTA, (R, M, N, K)), [2, 0, 3, 1])  # N x R x K x M
            fvar = fvar[:, None, :, :] + tf.matmul(LTAr, LTAr, transpose_b=True)  # N x R x K x K
        elif not full_cov and not full_cov_output:
            addvar = tf.reshape(tf.reduce_sum(tf.square(LTA), 1), (R, N, K))
            fvar = fvar[:, None, :] + tf.transpose(addvar, (1, 0, 2))  # N x R x K
    return fmean, fvar
