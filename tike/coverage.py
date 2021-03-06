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
This module contains functions for determining the coverage of a scanning
trajectory.
"""
from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import numpy as np
from . import utils
from tike.externs import LIBTIKE
import logging
import ctypes

__author__ = "Doga Gursoy, Daniel Ching"
__copyright__ = "Copyright (c) 2018, UChicago Argonne, LLC."
__docformat__ = "restructuredtext en"
__all__ = ["coverage"]


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _coverage_interface(object_grid, object_min, object_size,
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
    # different from _tomo_interface
    assert theta.size == h.size == v.size, \
        "The size of theta, h, v must be the same as the number of probes."
    # logger.info(" _tomo_interface says {}".format("Hello, World!"))
    return (object_grid, object_min, object_size,
            probe_grid, probe_size, theta, h, v)


def coverage(object_grid, object_min, object_size,
             probe_grid, probe_size, theta, h, v,
             dwell=None, **kwargs):
    """Return a coverage map using this probe.

    The intersection between each line and each pixel is approximated by
    the product of `line_width**2` and the length of segment of the
    line segment `alpha` which passes through the pixel along the line.

    Parameters
    ----------
    theta, h, v [radians, cm]
        The positions of the min_corner of the probe.
    dwell : (M, ) :py:class:`numpy.array` [s]
        Multiply the intersections lengths of the pixels and each line by these
        weights.

    Returns
    -------
    coverage_map : :py:class:`numpy.ndarray` [s]
        An array of shape (ngrid, anisotropy) containing the sum of the
        intersection lengths multiplied by the line_weights.
        A discretized map of the approximated procedure coverage.
    """
    object_grid, object_min, object_size, probe_grid, probe_size, theta, h, v \
        = _coverage_interface(object_grid, object_min, object_size,
                              probe_grid, probe_size, theta, h, v)
    ngrid = object_grid.shape
    assert len(ngrid) == 4, "Coverage map must have 4 dimensions."
    # Multiply the trajectory by size of probe_grid
    dh, dv = line_offsets(probe_grid, probe_size)
    th1 = np.repeat(theta, dh.size)
    h1 = np.repeat(h, dh.size).reshape(h.size, dh.size) + dh
    v1 = np.repeat(v, dv.size).reshape(v.size, dv.size) + dv
    if dwell is None:
        dw1 = np.ones(th1.shape)
    else:
        dw1 = np.repeat(dwell, dv.size)
    # Computer other parameters for c funcion
    line_area = np.prod(probe_size / probe_grid.shape)
    pixel_volume = np.prod(object_size / object_grid.shape[0:3])
    weights = dw1 * line_area / pixel_volume  # [s m^2 / m^3]
    logger.info(" coverage {:,d} element grid".format(object_grid.size))
    # Send data to c function
    th1 = utils.as_float32(th1)
    h1 = utils.as_float32(h1)
    v1 = utils.as_float32(v1)
    weights = utils.as_float32(weights)
    object_grid = utils.as_float32(object_grid)
    LIBTIKE.coverage.restype = utils.as_c_void_p()
    LIBTIKE.coverage(
        utils.as_c_float(object_min[0]),
        utils.as_c_float(object_min[1]),
        utils.as_c_float(object_min[2]),
        utils.as_c_float(object_size[0]),
        utils.as_c_float(object_size[1]),
        utils.as_c_float(object_size[2]),
        utils.as_c_int(ngrid[0]),
        utils.as_c_int(ngrid[1]),
        utils.as_c_int(ngrid[2]),
        utils.as_c_int(ngrid[3]),
        utils.as_c_float_p(th1),
        utils.as_c_float_p(h1),
        utils.as_c_float_p(v1),
        utils.as_c_float_p(weights),
        utils.as_c_int(th1.size),
        utils.as_c_float_p(object_grid))
    return object_grid


def line_offsets(probe_grid, probe_size):
    """Generate h, v line offsets from the min corner and filter
    zero-weighted lines.

    Returns
    -------
    dh, dv : (N, ) np.array [cm]
        The offsets in the horizontal and vertical directions
    """
    # Generate a grid of offset vectors
    gh = (np.linspace(0, probe_size[0], probe_grid.shape[0], endpoint=False)
          + probe_size[0] / probe_grid.shape[0] / 2)
    gv = (np.linspace(0, probe_size[1], probe_grid.shape[1], endpoint=False)
          + probe_size[1] / probe_grid.shape[1] / 2)
    dh, dv = np.meshgrid(gh, gv, indexing='ij')
    # Remove zero values
    nonzeros = probe_grid != 0
    h = dh[nonzeros].flatten()
    v = dv[nonzeros].flatten()
    logger.info(" probe uses {:,d} lines".format(h.size))
    assert dv.size == dh.size
    return h, v
