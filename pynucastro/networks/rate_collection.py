"""A collection of classes and methods to deal with collections of
rates that together make up a network."""

# Common Imports
from __future__ import print_function

import functools
import glob
import math
from operator import mul
import os

from ipywidgets import interact

import matplotlib
import matplotlib.pyplot as plt
import networkx as nx

# Import Rate
from pynucastro.rates import Rate, Nucleus, Library

matplotlib.rcParams['figure.dpi'] = 100

class Composition(object):
    """a composition holds the mass fractions of the nuclei in a network
    -- useful for evaluating the rates

    """
    def __init__(self, nuclei, small=1.e-16):
        """nuclei is an iterable of the nuclei (Nucleus objects) in the network"""
        if not isinstance(nuclei[0], Nucleus):
            raise ValueError("must supply an iterable of Nucleus objects")
        else:
            self.X = {k: small for k in nuclei}

    def set_solar_like(self, Z=0.02):
        """ approximate a solar abundance, setting p to 0.7, He4 to 0.3 - Z and
        the remainder evenly distributed with Z """
        num = len(self.X)
        rem = Z/(num-2)
        for k in self.X:
            if k == Nucleus("p"):
                self.X[k] = 0.7
            elif k.raw == "he4":
                self.X[k] = 0.3 - Z
            else:
                self.X[k] = rem

        self.normalize()

    def set_all(self, xval):
        """ set all species to a particular value """
        for k in self.X:
            self.X[k] = xval

    def set_nuc(self, name, xval):
        """ set nuclei name to the mass fraction xval """
        for k in self.X:
            if k.raw == name:
                self.X[k] = xval
                break

    def normalize(self):
        """ normalize the mass fractions to sum to 1 """
        X_sum = sum([self.X[k] for k in self.X])

        for k in self.X:
            self.X[k] /= X_sum

    def get_molar(self):
        """ return a dictionary of molar fractions"""
        molar_frac = {k: v/k.A for k, v in self.X.items()}
        return molar_frac

    def __str__(self):
        ostr = ""
        for k in self.X:
            ostr += "  X({}) : {}\n".format(k, self.X[k])
        return ostr

class RateCollection(object):
    """ a collection of rates that together define a network """

    pynucastro_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))

    def __init__(self, rate_files=None, libraries=None, rates=None):
        """
        rate_files are the files that together define the network.  This
        can be any iterable or single string.

        This can include Reaclib library files storing multiple rates.

        If libraries is supplied, initialize a RateCollection using the rates 
        in the Library object(s) in list 'libraries'.

        If rates is supplied, initialize a RateCollection using the 
        Rate objects in the list 'rates'.

        Any combination of these options may be combined.
        """

        self.files = []
        self.rates = []
        self.library = None

        if rate_files:
            if isinstance(rate_files, str):
                rate_files = [rate_files]
            self._read_rate_files(rate_files)

        if rates:
            if isinstance(rates, Rate):
                rates = [rates]
            try:
                for r in rates:
                    assert(isinstance(r, Rate))
            except:
                print('Expected Rate object or list of Rate objects passed as the rates argument.')
                raise
            else:
                rlib = Library(rates=rates)
                if not self.library:
                    self.library = rlib
                else:
                    self.library = self.library + rlib

        if libraries:
            if isinstance(libraries, Library):
                libraries = [libraries]
            try:
                for lib in libraries:
                    assert(isinstance(lib, Library))
            except:
                print('Expected Library object or list of Library objects passed as the libraries argument.')
                raise
            else:
                if not self.library:
                    self.library = libraries.pop(0)
                for lib in libraries:
                    self.library = self.library + lib

        if self.library:
            self.rates = self.rates + self.library.get_rates()

        # get the unique nuclei
        u = []
        for r in self.rates:
            t = set(r.reactants + r.products)
            u = set(list(u) + list(t))

        self.unique_nuclei = sorted(u)

        # now make a list of each rate that touches each nucleus
        # we'll store this in a dictionary keyed on the nucleus
        self.nuclei_consumed = {}
        self.nuclei_produced = {}

        for n in self.unique_nuclei:
            self.nuclei_consumed[n] = [r for r in self.rates if n in r.reactants]
            self.nuclei_produced[n] = [r for r in self.rates if n in r.products]

        # Re-order self.rates so Reaclib rates come first,
        # followed by Tabular rates. This is needed if
        # reaclib coefficients are targets of a pointer array
        # in the Fortran network.
        # It is desired to avoid wasting array size
        # storing meaningless Tabular coefficient pointers.
        self.rates = sorted(self.rates,
                            key=lambda r: r.chapter == 't')

        self.tabular_rates = []
        self.reaclib_rates = []
        for n, r in enumerate(self.rates):
            if r.chapter == 't':
                self.tabular_rates.append(n)
            elif isinstance(r.chapter, int):
                self.reaclib_rates.append(n)
            else:
                print('ERROR: Chapter type unknown for rate chapter {}'.format(
                    str(r.chapter)))
                exit()

    def _read_rate_files(self, rate_files):
        # get the rates
        self.files = rate_files
        for rf in self.files:
            try:
                rflib = Library(rf)
            except:
                print("Error reading library from file: {}".format(rf))
                raise
            else:
                if not self.library:
                    self.library = rflib
                else:
                    self.library = self.library + rflib

    def get_nuclei(self):
        """ get all the nuclei that are part of the network """
        return self.unique_nuclei

    def evaluate_rates(self, rho, T, composition):
        """evaluate the rates for a specific density, temperature, and
        composition"""
        rvals = {}
        ys = composition.get_molar()

        for r in self.rates:
            val = r.prefactor * rho**r.dens_exp * r.eval(T)
            yfac = functools.reduce(mul, [ys[q] for q in r.reactants])
            rvals[r] = yfac * val

        return rvals

    def network_overview(self):
        """ return a verbose network overview """
        ostr = ""
        for n in self.unique_nuclei:
            ostr += "{}\n".format(n)
            ostr += "  consumed by:\n"
            for r in self.nuclei_consumed[n]:
                ostr += "     {}\n".format(r.string)

            ostr += "  produced by:\n"
            for r in self.nuclei_produced[n]:
                ostr += "     {}\n".format(r.string)

            ostr += "\n"
        return ostr

    def write_network(self, *args, **kwargs):
        """Before writing the network, check to make sure the rates
        are distinguishable by name."""
        assert self._distinguishable_rates(), "ERROR: Rates not uniquely identified by Rate.fname"
        self._write_network(*args, **kwargs)

    def _distinguishable_rates(self):
        """Every Rate in this RateCollection should have a unique Rate.fname,
        as the network writers distinguish the rates on this basis."""
        names = [r.fname for r in self.rates]
        return len(set(names)) == len(self.rates)

    def _write_network(self, *args, **kwargs):
        """A stub for function to output the network -- this is implementation
        dependent."""
        print('To create network integration source code, use a class that implements a specific network type.')
        return

    def plot(self, outfile=None, rho=None, T=None, comp=None, size=(800, 600), dpi=100):
        """Make a plot of the network structure showing the links between nuclei"""

        G = nx.MultiDiGraph()
        G.position = {}
        G.labels = {}

        plt.plot([0, 0], [8, 8], 'b-')

        # nodes -- the node nuclei will be all of the heavies, but not
        # p, n, alpha, unless we have p + p, 3-a, etc.
        node_nuclei = []
        for n in self.unique_nuclei:
            if n.raw not in ["p", "n", "he4"]:
                node_nuclei.append(n)
            else:
                for r in self.rates:
                    if r.reactants.count(n) > 1:
                        node_nuclei.append(n)
                        break

        for n in node_nuclei:
            G.add_node(n)
            G.position[n] = (n.N, n.Z)
            G.labels[n] = r"${}$".format(n.pretty)

        if rho is not None and T is not None and comp is not None:
            ydots = self.evaluate_rates(rho, T, comp)
        else:
            ydots = None

        #for rr in ydots:
        #    print("{}: {}".format(rr, ydots[rr]))

        # edges
        for n in node_nuclei:
            for r in self.nuclei_consumed[n]:
                for p in r.products:
                    if p in node_nuclei:
                        # networkx doesn't seem to keep the edges in
                        # any particular order, so we associate data
                        # to the edges here directly, in this case,
                        # the reaction rate, which will be used to
                        # color it
                        if ydots is None:
                            G.add_edges_from([(n, p)], weight=0.5)
                        else:
                            try:
                                rate_weight = math.log10(ydots[r])
                            except ValueError:
                                # if ydots[r] is zero, then set the weight
                                # to roughly the minimum exponent possible
                                # for python floats
                                rate_weight = -308
                            except:
                                raise
                            G.add_edges_from([(n, p)], weight=rate_weight)

        nx.draw_networkx_nodes(G, G.position,
                               node_color="#A0CBE2", alpha=1.0,
                               node_shape="o", node_size=1000, linewidth=2.0, zorder=10)

        nx.draw_networkx_labels(G, G.position, G.labels,
                                font_size=13, font_color="w", zorder=100)

        # get the edges and weights coupled in the same order
        edges, weights = zip(*nx.get_edge_attributes(G, 'weight').items())

        edges_lc = nx.draw_networkx_edges(G, G.position, width=3,
                                          edgelist=edges, edge_color=weights,
                                          edge_cmap=plt.cm.viridis, zorder=1)

        # draw_networkx_edges returns a LineCollection matplotlib type
        # which we can use for the colorbar
        if ydots is not None:
            plt.colorbar(edges_lc)

        Zs = [n.Z for n in node_nuclei]

        plt.xlim(min(Zs)-1, max(Zs)+1)
        plt.xlabel(r"$N$", fontsize="large")
        plt.ylabel(r"$Z$", fontsize="large")

        ax = plt.gca()
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.spines['right'].set_visible(False)
        ax.spines['top'].set_visible(False)
        ax.xaxis.set_ticks_position('bottom')
        ax.yaxis.set_ticks_position('left')

        ax = plt.gca()
        ax.set_aspect("equal", "datalim")

        f = plt.gcf()
        f.set_size_inches(size[0]/dpi, size[1]/dpi)

        if outfile is None:
            plt.show()
        else:
            plt.tight_layout()
            plt.savefig(outfile, dpi=dpi)

    def __repr__(self):
        string = ""
        for r in self.rates:
            string += "{}\n".format(r.string)
        return string


class Explorer(object):
    """ interactively explore a rate collection """
    def __init__(self, rc, comp, size=(800, 600)):
        """ take a RateCollection and a composition """
        self.rc = rc
        self.comp = comp
        self.size = size

    def _make_plot(self, logrho, logT):
        self.rc.plot(rho=10.0**logrho, T=10.0**logT, comp=self.comp, size=self.size)

    def explore(self):
        """Perform interactive exploration of the network structure."""
        interact(self._make_plot, logrho=(2, 6, 0.1), logT=(7, 9, 0.1))
