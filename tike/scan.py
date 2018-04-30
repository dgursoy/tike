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
Module for 3D scanning.

Coverage Workflow
-----------------

1. User defines a function in `thetahv` space. `user_func(t) -> [theta,h,v]`

2. Using the `density_profile` of the probe in the `h, v` plane, create a
    weighted list of thick lines to represent the `Probe`.

3. For each lines, wrap the user function in an offset function.
    `lines_offset(user_func(t)) -> [theta,h,v]`

5. Send the wrapped functions to `discrete_trajectory` to generate a list of
    lines positions which need to be added to the coverage map.

6. Send the list of line positions with their weights to the coverage
    approximator. Weights are used to approximate the density profile of the
    probe.
"""

from __future__ import (absolute_import, division, print_function,
                        unicode_literals)

import numpy as np
import logging
import warnings
from tqdm import tqdm
from tike.tomo import coverage

__author__ = "Doga Gursoy"
__copyright__ = "Copyright (c) 2018, UChicago Argonne, LLC."
__docformat__ = 'restructuredtext en'
__all__ = ['scantime',
           'sinusoid',
           'triangle',
           'sawtooth',
           'square',
           'staircase',
           'lissajous',
           'raster',
           'spiral',
           'scan3',
           'avgspeed',
           'lengths',
           'distance',
           'Probe',
           'coverage_approx',
           'discrete_trajectory']


logger = logging.getLogger(__name__)


class Probe(object):
    """Generates procedures for coverage metrics.

    `Probe` moves in a 3D coordinate system: `theta, h, v`. `h, v` are the
    horizontal vertical directions perpendiclar to the probe direction
    where positive directions are to the right and up respectively. `theta` is
    the rotation angle around the vertical reconstruction space axis, `z`. `z`
    is parallel to `v`, and uses the right hand rule to determine
    reconstruction space coordinates `x, y, z`. `theta` is measured from the
    `x` axis, so when `theta = 0`, `h` is parallel to `y`.

    The default probe is a 1 mm^2 square of uniform intensity.

    Attributes
    ----------
    density_profile : function(h, v) -> intensity
        A function that describes the intensity of the beam in the `h, v`
        plane, centered on `[0, 0]`.
    extent : :py:class:`np.array` [cm]
        A rectangle confining the `Probe`. Specify width and aspect ratio.
    """
    def __init__(self, density_profile=None, width=None, aspect=None):
        if density_profile is None:
            self.density_profile = lambda h, v: 1
        else:
            self.density_profile = density_profile
        if width is None:
            self.width = 0.1
            self.aspect = 1
        else:
            self.width = width
            self.aspect = aspect
        self.line_width = 1

    def line_offsets(self, pixel_size, N=1):
        """Generate a list of ray offsets and weights from density profile
        and extent.

        From a previous study, we determined that the `line_width` should be at
        most 1/16 of the pixel size.

        Returns
        -------
        rays : array [cm]
            [([theta, h, v], intensity_weight), ...]
        """
        # return [([0, 0, 0], 1), ]  # placeholder
        width, height = self.width, self.width * self.aspect
        # determine if the probe extent is larger than the maximum line_width
        self.line_width = pixel_size/16
        if width < self.line_width or height < self.line_width:
            # line_width needs to shrink to fit within probe
            raise NotImplementedError("Why are you using such large pixels?")
        else:
            # probe is larger than line_width
            ncells = np.ceil(width / self.line_width)
            self.line_width = width / ncells
        gh = (np.linspace(0, width, int(width/self.line_width), endpoint=False)
              + (self.line_width - width) / 2)
        gv = (np.linspace(0, height, int(height/self.line_width),
                          endpoint=False)
              + (self.line_width - height) / 2)
        offsets = np.meshgrid(gh, gv, indexing='xy')
        h = offsets[0].flatten()
        v = offsets[1].flatten()
        thv = np.stack([np.zeros(v.shape), h, v], axis=1)
        lines = list()
        for row in thv:
            lines.append((row, self.density_profile(row[1], row[2])))
        return lines

    def procedure(self, trajectory, pixel_size, tmin, tmax, dt):
        """Return the discrete procedure description from the given trajectory.

        Parameters
        ----------
        trajectory : function(t) -> [theta, h, v]
            A function which describes the position of the center of the Probe
            as a function of time.
        pixel_size : float [cm]
            The edge length of the pixels in the coverage map. Underestimate
            if you don't know.

        Returns
        -------
        procedure : list of :py:class:`np.array` [radians, cm, ..., s]
            A (M,4) array which describes a series of lines:
            `[theta, h, v, weight]` to approximate the trajectory
        """
        positions = list()
        lines = self.line_offsets(pixel_size=pixel_size)
        dx = self.line_width
        # TODO: Each iteration of this loop is a separate line. If two or more
        # lines have the same h coordinate, then their discrete trajectories
        # parallel and offset in the v direction. #optimization
        for offset, weight in tqdm(lines):
            def line_trajectory(t):
                return trajectory(t) + offset
            position, dwell, none = discrete_trajectory(trajectory=line_trajectory,
                                                        tmin=tmin, tmax=tmax,
                                                        dx=dx, dt=dt)
            position = np.concatenate([position,
                                       np.atleast_2d(dwell * weight).T],
                                      axis=1)
            positions.append(position)
        return positions

    def coverage(self, trajectory, region, pixel_size, tmin, tmax, dt,
                 anisotropy=False):
        """Return a coverage map using this probe.

        trajectory : function(t) -> [theta, h, v] [radians, cm]
            A function which describes the position of the center of the Probe
            as a function of time.
        region : :py:class:`np.array` [cm]
            A box in which to map the coverage. Specify the bounds as
            `[[min_x, max_x], [min_y, max_y], [min_z, max_z]]`.
            i.e. column vectors pointing to the min and max corner.
        pixel_size : float [cm]
            The edge length of the pixels in the coverage map.
        """
        procedure = self.procedure(trajectory=trajectory,
                                   pixel_size=pixel_size, tmin=tmin, tmax=tmax,
                                   dt=dt)
        procedure = np.concatenate(procedure)
        return coverage_approx(procedure=procedure, region=region,
                               pixel_size=pixel_size,
                               line_width=self.line_width,
                               anisotropy=anisotropy)


def coverage_approx(procedure, region, pixel_size, line_width,
                    anisotropy=False):
    """Approximate procedure coverage with thick lines.

    The intersection between each line and each pixel is approximated by
    the product of `line_width**2` and the length of segment of the
    line segment `alpha` which passes through the pixel along the line.

    If `anisotropy` is `True`, then `coverage_map.shape` is `(L, M, N, 2, 2)`,
    where the two extra dimensions contain coverage anisotropy information as a
    second order tensor.

    Parameters
    ----------
    procedure : list of :py:class:`np.array` [rad, cm, ..., s]
        Each element of 'procedure' is a (4,) array which describes a series
        of lines as `[theta, h, v, weight]`.
    line_width` : float [cm]
        The side length of the square cross-section of the line.
    region : :py:class:`np.array` [cm]
        A box in which to map the coverage. Specify the bounds as
        `[[min_x, max_x], [min_y, max_y], [min_z, max_z]]`.
        i.e. column vectors pointing to the min and max corner. Bounds should
        be an integer multiple of the pizel_size.
    pixel_size : float [cm]
        The edge length of the pixels in the coverage map in centimeters.
    anisotropy : bool
        Determines whether the coverage map includes anisotropy information.

    Returns
    -------
    coverage_map : :py:class:`numpy.ndarray` [s]
        A discretized map of the approximated procedure coverage.
    """
    # define integer range of region of interest
    box = np.asanyarray(region)
    assert np.all(box[:, 0] <= box[:, 1]), ("region minimum must be <= to"
                                            "region maximum.")
    if np.any(box % pixel_size != 0):
        warnings.warn("Probe.coverage_approx: Region bounds will be shifted to"
                      "an integer multiple of the pixel_size.", UserWarning)
    ibox = box / pixel_size
    ibox[:, 0] = np.floor(ibox[:, 0])
    ibox[:, 1] = np.ceil(ibox[:, 1])
    ibox_shape = (ibox[:, 1] - ibox[:, 0]).astype(int)
    # Preallocate the coverage_map
    if anisotropy:
        raise NotImplementedError
        coverage_map = np.zeros([list(ibox_shape), 2, 2])
    else:
        coverage_map = np.zeros(ibox_shape)
    # Format the data for the c_functions
    procedure = np.array(procedure)
    # Scale to a coordinate system where pixel_size is 1.0
    h, v = procedure[:, 1], procedure[:, 2]
    h /= pixel_size
    v /= pixel_size
    w = procedure[:, 3] * line_width**2 / pixel_size**2
    # Shift coordinates so region aligns with pixel grid
    # WONTFIX: Cannot shift coords to align with requested region without
    # moving the rotation center.
    coverage_map = coverage(coverage_map, theta=procedure[:, 0], h=h, v=v,
                            line_weight=w)
    return coverage_map


def f2w(f):
    return 2*np.pi*f


def period(f):
    return 1 / f


def exposure(hz):
    return 1 / hz


def scantime(t, hz):
    return np.linspace(0, t, t*hz)


def sinusoid(A, f, p, t, hz):
    """Continuous"""
    w = f2w(f)
    p = np.mod(p, 2*np.pi)
    return A * np.sin(w*t - p)


def triangle(A, f, p, t, hz):
    """Continuous"""
    a = 0.5 * period(f)
    ts = t - p/(2*np.pi)/f
    q = np.floor(ts/a + 0.5)
    return A * (2/a * (ts - a*q) * np.power(-1, q))


def sawtooth(A, f, p, t, hz):
    """Discontinuous"""
    a = 0.5 * period(f)
    ts = t - p/(2*np.pi)/f
    q = np.floor(ts/a + 0.5)
    return A * (2 * (ts/a - q))


def square(A, f, p, t, hz):
    """Discontinuous"""
    ts = t - p/(2*np.pi)/f
    return A * (np.power(-1, np.floor(2*f*ts)))


def staircase(A, f, p, t, hz):
    """Discontinuous"""
    ts = t - p/(2*np.pi)/f
    return A/f/2 * np.floor(2*f*ts) - A


def lissajous(A, B, fx, fy, px, py, time, hz):
    t = scantime(time, hz)
    x = sinusoid(A, fx, px, t, hz)
    y = sinusoid(B, fy, py, t, hz)
    return x, y, t


def raster(A, B, fx, fy, px, py, time, hz):
    t = scantime(time, hz)
    x = triangle(A, fx, px, t, hz)
    y = staircase(B, fy, py, t, hz)
    return x, y, t


def spiral(A, B, fx, fy, px, py, time, hz):
    t = scantime(time, hz)
    x = sawtooth(A, 0.5*fx, px, t, hz)
    y = sawtooth(B, 0.5*fy, py, t, hz)
    return x, y, t


def scan3(A, B, fx, fy, fz, px, py, time, hz):
    x, y, t = lissajous(A, B, fx, fy, px, py, time, hz)
    z = sawtooth(np.pi, 0.5*fz, 0.5*np.pi, t, hz)
    return x, y, z, t


def avgspeed(time, x, y=None, z=None):
    return distance(x, y, z) / time


def lengths(x, y=None, z=None):
    if y is None:
        y = np.zeros(x.shape)
    if z is None:
        z = np.zeros(x.shape)
    a = np.diff(x)
    b = np.diff(y)
    c = np.diff(z)
    return np.sqrt(a*a + b*b + c*c)


def distance(x, y=None, z=None):
    d = lengths(x, y, z)
    return np.sum(d)


def euclidian_dist(a, b):
    """Return the distance euclidian"""
    d = thetahv_to_xyz(a) - thetahv_to_xyz(b)
    return np.sqrt(d.dot(d))


def thetahv_to_xyz(thv_coords, radius=0.75):
    """Convert `theta, h, v` coordinates to `x, y, z` coordinates.

    Parameters
    ----------
    thv_coords : :py:class:`np.array` [radians, cm, cm]
        The coordinates in `theta, h, v` space.
    radius : float [cm]
        The radius used to place the `h, v` plane in `x, y, z` space.
        The default value is 0.75 because it is slightly larger than the radius
        of a unit square centered at the origin.
    """
    R, theta = np.eye(3), thv_coords[0]
    R[0, 0] = np.cos(theta)
    R[0, 1] = -np.sin(theta)
    R[1, 0] = np.sin(theta)
    R[1, 1] = np.cos(theta)
    return np.dot([radius, thv_coords[1], thv_coords[2]], R)


def discrete_trajectory(trajectory, tmin, tmax, dx, dt, max_iter=16):
    """Compute positions along the `trajectory` between `tmin` and `tmax` such
    that space between measurements is never more than `dx` and the time
    between measurements is never more than `dt`.

    Parameters
    ----------
    trajectory : function(time) -> [theta, h, v]
        A *continuous* function taking one input and returns a (N,) vector
        describing position of the line.
    [tmin, tmax) : float
        The start and end times.
    dx : float
        The maximum spatial step size.
    dt : float
        The maximum time step size.
    max_iter : int
        The number of attempts to allowed to find a step less than
        `dx` and `dt`.

    Returns
    -------
    position : list of (N,) vectors [m]
        Discrete measurement positions along the trajectory satisfying
        constraints.
    dwell : list of float [s]
        The time spent at each position before moving to the next measurement.
    time : list of float [s]
        Discrete times along trajectory satisfying constraints.

    Implementation
    --------------
    Keeping time steps below `dt` for 'trajectory(time)' is trivial, but
    keeping displacement steps below `dx` is not. We use the following
    assumption and proof to ensure that any the probe does not move more than
    `dx` within the area of interest.

    Given that `x` is a point on the line segment `AB` between the endpoints a
    and `b`. Prove that for all affine transformations of `AB`, `AB' = T(AB)`,
    the magnitude of displacement, `dx` is less than or equal to `da` or `db`.

    [TODO: Insert proof here.]

    Thus, if at all times, both points used to define the
    probe remains outside the region of interest, then it can be said that
    probe movement within the area of interest is less than dx or equal to dx
    by controlling the movement of the end points of the probe. The users is
    responsible for checking whether the output conforms to this constraint.

    Measurements along the trajectory are generated using a binary search.
    First a starting point is generated, then the time is incremented by `dt`
    is generated, if this point is too farther than `dx` from the previous,
    another point is generated recursively between the previous two.
    """
    position, time, dwell, nextxt = list(), list(), list(), list()
    t, tnext = tmin, min(tmin + dt, tmax)
    x = trajectory(t)
    while t < tmax:
        if not nextxt:
            xnext = trajectory(tnext)
        elif len(nextxt) > max_iter:
            raise RuntimeError("Failed to find next step within {} tries. "
                               "Probably the function is discontinuous."
                               .format(max_iter))
        else:
            xnext, tnext = nextxt.pop()
        if euclidian_dist(xnext, x) <= dx:
            position.append(x)
            time.append(t)
            dwell.append(tnext - t)
            x, t = xnext, tnext
            tnext = min(t + dt, tmax)
        else:
            nextxt.append((xnext, tnext))
            tnext = (tnext + t) / 2
            nextxt.append((trajectory(tnext), tnext))

    return position, dwell, time
