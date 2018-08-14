#!/usr/bin/env python
# -*- coding: utf-8 -*-

# #########################################################################
# Copyright (c) 2017-2018, UChicago Argonne, LLC. All rights reserved.    #
#                                                                         #
# Copyright 2018. UChicago Argonne, LLC. This software was produced       #
# under U.S. Government contract DE-AC02-06CH11357 for Argonne National   #
# Laboratory (ANL), which is operated by UChicago Argonne, LLC for the    #
# U.S. Department of Energy. The U.S. Government has rights to use,       #
# reproduce, and distribute this software.  NEITHER THE GOVERNMENT NOR    #
# UChicago Argonne, LLC MAKES ANY WARRANTY, EXPRESS OR IMPLIED, OR        #
# ASSUMES ANY LIABILITY FOR THE USE OF THIS SOFTWARE.  If software is     #
# modified to produce derivative works, such modified software should     #
# be clearly marked, so as not to confuse it with the version available   #
# from ANL.                                                               #
#                                                                         #
# Additionally, redistribution and use in source and binary forms, with   #
# or without modification, are permitted provided that the following      #
# conditions are met:                                                     #
#                                                                         #
#     * Redistributions of source code must retain the above copyright    #
#       notice, this list of conditions and the following disclaimer.     #
#                                                                         #
#     * Redistributions in binary form must reproduce the above copyright #
#       notice, this list of conditions and the following disclaimer in   #
#       the documentation and/or other materials provided with the        #
#       distribution.                                                     #
#                                                                         #
#     * Neither the name of UChicago Argonne, LLC, Argonne National       #
#       Laboratory, ANL, the U.S. Government, nor the names of its        #
#       contributors may be used to endorse or promote products derived   #
#       from this software without specific prior written permission.     #
#                                                                         #
# THIS SOFTWARE IS PROVIDED BY UChicago Argonne, LLC AND CONTRIBUTORS     #
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT       #
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS       #
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL UChicago     #
# Argonne, LLC OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,        #
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,    #
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;        #
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER        #
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT      #
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN       #
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE         #
# POSSIBILITY OF SUCH DAMAGE.                                             #
# #########################################################################

"""
This module contains functions for solving the tomography problem.

Coordinate Systems
==================
`theta, h, v`. `h, v` are the
horizontal vertical directions perpendicular to the probe direction
where positive directions are to the right and up respectively. `theta` is
the rotation angle around the vertical reconstruction space axis, `z`. `z`
is parallel to `v`, and uses the right hand rule to determine
reconstruction space coordinates `z, x, y`. `theta` is measured from the
`x` axis, so when `theta = 0`, `h` is parallel to `y`.

Functions
=========
Each function in this module should have the following interface:

Parameters
----------
object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
    An array of material properties. The first three dimensions `Z, X, Y`
    are spatial dimensions. The fourth dimension, `P`,  holds properties at
    each grid position: refractive indices, attenuation coefficents, etc.
object_min : (3, ) float
    The min corner (z, x, y) of `object_grid`.
object_size : (3, ) float
    The side lengths (z, x, y) of `object_grid` along each dimension.
probe_grid : (M, H, V, P) :py:class:`numpy.array` float
    The parameters of the `M` probes to be collected or projected across
    `object_grid`. The grid of each probe is `H` rays wide (the
    horizontal direction) and `V` rays tall (the vertical direction). The
    fourth dimension, `P`, holds parameters at each grid position:
    measured intensity, relative phase shift, etc.
probe_size : (2, ) float
    The side lengths (h, v) of `probe_grid` along each dimension. The
    dimensions of each slice of probe_grid is the same for simplicity.
theta, h, v : (M, ) :py:class:`numpy.array` float
    The min corner (theta, h, v) of each `M` slice of `probe_grid`.
kwargs
    Keyword arguments specific to this function.

Returns
-------
output : :py:class:`numpy.array`
    Output specific to this function matching conventions for input
    parameters.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import numpy as np
from . import utils
from tike.externs import LIBTIKE
import logging

__author__ = "Doga Gursoy, Daniel Ching"
__copyright__ = "Copyright (c) 2018, UChicago Argonne, LLC."
__docformat__ = 'restructuredtext en'
__all__ = ["reconstruct",
           "project_forward",
           "project_backward",
           "art",
           "sirt",
           ]


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _tomo_interface(object_grid, object_min, object_size,
                    probe_grid, probe_size, theta, h, v,
                    **kwargs):
    """A function whose interface all functions in this module matches.

    This function also sets default values for functions in this module.
    """
    if object_grid is None:
        raise ValueError()
    object_grid = utils.as_float32(object_grid)
    if object_min is None:
        object_min = (-0.5, -0.5, -0.5)
    object_min = utils.as_float32(object_min)
    if object_size is None:
        object_size = (1.0, 1.0, 1.0)
    object_size = utils.as_float32(object_size)
    if probe_grid is None:
        raise ValueError()
    probe_grid = utils.as_float32(probe_grid)
    if probe_size is None:
        probe_size = (1, 1)
    probe_size = utils.as_float32(probe_size)
    if theta is None:
        raise ValueError()
    theta = utils.as_float32(theta)
    if h is None:
        h = np.full(theta.shape, -0.5)
    h = utils.as_float32(h)
    if v is None:
        v = np.full(theta.shape, -0.5)
    v = utils.as_float32(v)
    assert np.all(object_size > 0), "Object dimensions must be > 0."
    assert np.all(probe_size > 0), "Probe dimensions must be > 0."
    assert theta.size == h.size == v.size == probe_grid.shape[0], \
        "The size of theta, h, v must be the same as the number of probes."
    # logging.info(" _tomo_interface says {}".format("Hello, World!"))
    return (object_grid, object_min, object_size,
            probe_grid, probe_size, theta, h, v)


def reconstruct(object_grid=None, object_min=None, object_size=None,
                probe_grid=None, probe_size=None,
                theta=None, h=None, v=None,
                algorithm=None, **kwargs):
    """Reconstruct the `object_grid` using the given `algorithm`.

    Parameters
    ----------
    object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        The initial guess for the reconstruction.

    Returns
    -------
    new_object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        The updated object grid.
    """
    object_grid, object_min, object_size, probe_grid, probe_size, theta, h, v \
        = _tomo_interface(object_grid, object_min, object_size,
                          probe_grid, probe_size, theta, h, v)
    assert niter >= 0, "Number of iterations should be >= 0"
    raise NotImplementedError()
    return new_object_grid


def project_forward(object_grid=None, object_min=None, object_size=None,
                    probe_grid=None, probe_size=None,
                    theta=None, h=None, v=None,
                    **kwargs):
    """Forward-project probes over an object; i.e. simulate data acquisition.

    Parameters
    ----------
    probe_grid : (M, H, V, P) :py:class:`numpy.array` float
        The inital parameters of the `M` probes to be projected across
        `object_grid`. `P`, holds parameters at each grid position:
            * (..., 0) : intensity / amplitude
            * (..., 1) : relative phase shift

    Returns
    -------
    exit_probe_grid : (M, H, V, P) :py:class:`numpy.array` float
        The properties of the probe after exiting the `object_grid`.
    """
    object_grid, object_min, object_size, probe_grid, probe_size, theta, h, v \
        = _tomo_interface(object_grid, object_min, object_size,
                          probe_grid, probe_size, theta, h, v)
    raise NotImplementedError()
    # obj = utils.as_float32(object_grid)
    # ngrid = obj.shape
    # theta = utils.as_float32(theta)
    # h = utils.as_float32(h)
    # v = utils.as_float32(v)
    # dsize = theta.size
    # data = np.zeros((dsize, ), dtype=np.float32)
    # externs.c_project(obj,
    #                   grid_min[0], grid_min[1], grid_min[2],
    #                   grid_size[0], grid_size[1], grid_size[2],
    #                   ngrid[0], ngrid[1], ngrid[2],
    #                   theta, h, v, dsize, data)
    # Import shared library.
    LIBTIKE.forward_project.restype = utils.as_c_void_p()
    return LIBTIKE.forward_project(
            utils.as_c_float_p(obj),
            utils.as_c_float(ozmin),
            utils.as_c_float(oxmin),
            utils.as_c_float(oymin),
            utils.as_c_float(zsize),
            utils.as_c_float(xsize),
            utils.as_c_float(ysize),
            utils.as_c_int(oz),
            utils.as_c_int(ox),
            utils.as_c_int(oy),
            utils.as_c_float_p(theta),
            utils.as_c_float_p(h),
            utils.as_c_float_p(v),
            utils.as_c_int(dsize),
            utils.as_c_float_p(data))
    return exit_probe_grid


def project_backward(object_grid, object_min, object_size,
                     probe_grid, probe_size, theta, h, v,
                     **kwargs):
    """Back-project a probe over an object.

    Parameters
    ----------
    probe_grid : (M, H, V, P) :py:class:`numpy.array` float
        The parameters of the `M` probes to be projected across
        `object_grid`. `P`, holds parameters at each grid position:
            * (..., 0) : 0th probe back-projection weight
            * (..., P-1) : (P-1)th probe back-projection weight

    Returns
    -------
    new_object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        An array of projection weights. The value at each grid position is the
        area of intersection of the object with the probe multiplied by the
        probe weight.
    """
    object_grid, object_min, object_size, probe_grid, probe_size, theta, h, v \
        = _tomo_interface(object_grid, object_min, object_size,
                          probe_grid, probe_size, theta, h, v)
    raise NotImplementedError()
    return new_object_grid


def art(object_grid, object_min, object_size,
        probe_grid, probe_size, theta, h, v,
        niter=1, **kwargs):
    """Reconstruct using Algebraic Reconstruction Technique (ART)

    See :cite:`gordon1970algebraic` for original description of ART.

    Parameters
    ----------
    object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        The initial guess for the reconstruction.
    niter : int
        The number of ART iterations to perform

    Returns
    -------
    new_object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        The updated object grid.
    """
    object_grid, object_min, object_size, probe_grid, probe_size, theta, h, v \
        = _tomo_interface(object_grid, object_min, object_size,
                          probe_grid, probe_size, theta, h, v)
    assert niter >= 0, "Number of iterations should be >= 0"
    raise NotImplementedError()
    # grid_min = utils.as_float32(grid_min)
    # grid_size = utils.as_float32(grid_size)
    # data = utils.as_float32(data)
    # theta = utils.as_float32(theta)
    # h = utils.as_float32(h)
    # v = utils.as_float32(v)
    # init = utils.as_float32(init)
    # nz, nx, ny = init.shape
    # logging.info(" ART {:,d} element grid for {:,d} iterations".format(
    #     init.size, niter))
    # externs.c_art(grid_min[0], grid_min[1], grid_min[2],
    #               grid_size[0], grid_size[1], grid_size[2],
    #               nz, nx, ny,
    #               data, theta, h, v, data.size, init, niter)
    LIBTIKE.art.restype = utils.as_c_void_p()
    return LIBTIKE.art(
            utils.as_c_float(ozmin),
            utils.as_c_float(oxmin),
            utils.as_c_float(oymin),
            utils.as_c_float(zsize),
            utils.as_c_float(xsize),
            utils.as_c_float(ysize),
            utils.as_c_int(oz),
            utils.as_c_int(ox),
            utils.as_c_int(oy),
            utils.as_c_float_p(data),
            utils.as_c_float_p(theta),
            utils.as_c_float_p(h),
            utils.as_c_float_p(v),
            utils.as_c_int(dsize),
            utils.as_c_float_p(recon),
            utils.as_c_int(n_iter))
    return new_object_grid


def sirt(object_grid, object_min, object_size,
         probe_grid, probe_size, theta, h, v,
         niter=1, **kwargs):
    """Reconstruct using Simultaneous Iterative Reconstruction Technique (SIRT)

    Parameters
    ----------
    object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        The initial guess for the reconstruction.
    niter : int
        The number of SIRT iterations to perform

    Returns
    -------
    new_object_grid : (Z, X, Y, P) :py:class:`numpy.array` float
        The updated object grid.
    """
    object_grid, object_min, object_size, probe_grid, probe_size, theta, h, v \
        = _tomo_interface(object_grid, object_min, object_size,
                          probe_grid, probe_size, theta, h, v)
    assert niter >= 0, "Number of iterations should be >= 0"
    raise NotImplementedError()
    # grid_min = utils.as_float32(grid_min)
    # grid_size = utils.as_float32(grid_size)
    # data = utils.as_float32(data)
    # theta = utils.as_float32(theta)
    # h = utils.as_float32(h)
    # v = utils.as_float32(v)
    # init = utils.as_float32(init)
    # nz, nx, ny = init.shape
    # logging.info(" SIRT {:,d} element grid for {:,d} iterations".format(
    #     init.size, niter))
    # externs.c_sirt(grid_min[0], grid_min[1], grid_min[2],
    #                grid_size[0], grid_size[1], grid_size[2],
    #                nz, nx, ny,
    #                data, theta, h, v, data.size, init, niter)
    return new_object_grid
