# -*- coding: utf-8 -*-
from __future__ import print_function, unicode_literals
from eight import *
from future.utils import python_2_unicode_compatible

from .maps import Map
from .geometry import (
    get_intersection,
    measure_area,
    measure_line,
    clean,
)
from .projection import project, wgs84, MOLLWEIDE
from logging.handlers import QueueHandler, QueueListener
from pyproj import Proj
from shapely.geometry import shape
from shapely.geos import TopologicalError
import datetime
import logging
import math
import multiprocessing
import pyprind
import time

area_mapping = {
    'point': lambda x, y: 1,
    'line': measure_line,
    'polygon': measure_area
}

kind_mapping = {
    'Polygon': 'polygon',
    'MultiPolygon': 'polygon',
    'LineString': 'line',
    'MultiLineString': 'line',
    'LinearRing': 'line',
    'Point': 'point',
    'MultiPoint': 'point',
}

class BetterBar(pyprind.ProgBar):
    def finish(self):
        if self.cnt == self.max_iter:
            return
        else:
            self.cnt = self.max_iter
            self._finish()

    def update(self, index=None):
        if index is None:
            super(pyprind.ProgBar, self).update()
        else:
            self.cnt = index
            self._print()
            self._finish()


def chunker(iterable, chunk_size):
    for i in range(0, len(iterable), chunk_size):
        yield list(iterable[i:i + chunk_size])


def logger_init():
    # Adapted from http://stackoverflow.com/a/34964369/164864
    logging_queue = multiprocessing.Queue()
    # this is the handler for all log records
    filename = "{}-{}.log".format(
        'pandarus-worker', datetime.datetime.now().strftime("%d-%B-%Y-%I-%M%p")
    )
    handler = logging.FileHandler(
        filename,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(lineno)d %(message)s"))

    # queue_listener gets records from the queue and sends them to the handler
    queue_listener = QueueListener(logging_queue, handler)
    queue_listener.start()

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    return queue_listener, logging_queue


def worker_init(logging_queue):
    # Needed to pass logging messages from child processes to a queue
    # handler which in turn passes them onto queue listener
    queue_handler = QueueHandler(logging_queue)
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logger.addHandler(queue_handler)


def intersection_calculation(from_map, from_objs, to_map, worker_id, to_meters=True):
    """Multiprocessing worker for map matching"""
    logging.info("""Starting intersection_calculation:
    from map: {}
    from objs: {} ({} to {})
    to map: {}
    worker id: {}""".format(from_map, len(from_objs or []) or 'all',
                            min(from_objs or [0]), max(from_objs or [0]),
                            to_map, worker_id))

    results = {}

    to_map = Map(to_map)
    if to_map.geometry not in ('Polygon', 'MultiPolygon'):
        raise ValueError("`to_map` geometry must be polygons")
    rtree_index = to_map.create_rtree_index()
    logging.info("Worker {}: Loaded `to` map.".format(worker_id))

    from_map = Map(from_map)
    try:
        kind = kind_mapping[from_map.geometry]
    except KeyError:
        raise ValueError("No valid geometry type in map {}".format(from_map))
    logging.info("Worker {}: Loaded `from` map.".format(worker_id))

    skip_projection = (from_map.crs == to_map.crs) or \
        (Proj(wgs84(from_map.crs)).is_latlong() and \
         Proj(wgs84(to_map.crs)).is_latlong())

    if from_objs:
        from_gen = ((index, from_map[index]) for index in from_objs)
    else:
        from_gen = enumerate(from_map)

    if to_meters:
        meter_projection = lambda x: project(x, to_map.crs, MOLLWEIDE)
    else:
        meter_projection = None

    for from_index, from_obj in from_gen:
        try:
            geom = clean(shape(from_obj['geometry']))

            if not skip_projection:
                geom = project(geom, from_map.crs, to_map.crs)

            for k, v in get_intersection(
                geom,
                kind,
                to_map,
                rtree_index.intersection(geom.bounds),
                meter_projection
            ).items():
                results[(from_index, k)] = v

        except TopologicalError:
            logging.exception("Skipping topological error.")
            continue
        except:
            logging.exception("Intersection worker failed.")
            raise

    return results


def areal_calculation(from_map, from_objs, worker_id, to_meters=True):
    """Multiprocessing worker for areas of each object in a map"""
    logging.info("""Starting areal calculation:
    from map: {}
    from objs: {} ({} to {})
    worker id: {}""".format(from_map, len(from_objs or []) or 'all',
                            min(from_objs or [0]), max(from_objs or [0]),
                            worker_id))

    results = {}

    from_map = Map(from_map)
    try:
        kind = kind_mapping[from_map.geometry]
    except KeyError:
        raise ValueError("No valid geometry type in map {}".format(from_map))
    logging.info("Worker {}: Loaded from map.".format(worker_id))

    if from_objs:
        from_gen = ((index, from_map[index]) for index in from_objs)
    else:
        from_gen = enumerate(from_map)

    if to_meters:
        meter_projection = lambda x: project(x, from_map.crs, MOLLWEIDE)
    else:
        meter_projection = None

    for from_index, from_obj in from_gen:
        try:
            geom = clean(shape(from_obj['geometry']))

            results[from_index] = area_mapping[kind](geom, meter_projection)

        except TopologicalError:
            logging.exception("Skipping topological error.")
            continue
        except:
            logging.exception("Intersection worker failed.")
            raise

    return results


def raster_matcher(from_map, from_objs, to_map, raster_fp, worker_id):
    """Multiprocessing worker for map matching"""
    logging.info("""Starting `raster_matcher`:
    from map: {}
    from objs: {} ({} to {})
    to map: {}
    raster_fp: {}
    worker id: {}""".format(
        from_map, len(from_objs or []) or 'all',
        min(from_objs or [0]), max(from_objs or [0]),
        raster_fp, to_map, worker_id
    ))

    results = []

    to_map = Map(to_map)
    if to_map.geometry not in ('Polygon', 'MultiPolygon'):
        raise ValueError("`to_map` geometry must be polygons")
    rtree_index = to_map.create_rtree_index()
    logging.info("Worker {}: Loaded `to` map.".format(worker_id))

    from_map = Map(from_map)
    try:
        kind = kind_mapping[from_map.geometry]
    except KeyError:
        raise ValueError("No valid geometry type in map {}".format(from_map))
    logging.info("Worker {}: Loaded `from` map.".format(worker_id))

    skip_projection = (from_map.crs == to_map.crs) or \
        (Proj(wgs84(from_map.crs)).is_latlong() and \
         Proj(wgs84(to_map.crs)).is_latlong())

    if from_objs:
        from_gen = ((index, from_map[index]) for index in from_objs)
    else:
        from_gen = enumerate(from_map)

    if to_meters:
        meter_projection = lambda x: project(x, to_map.crs, MOLLWEIDE)
    else:
        meter_projection = None

    for from_index, from_obj in from_gen:
        try:
            geom = shape(from_obj['geometry'])

            if not geom.is_valid:
                geom = geom.buffer(0)
            if not skip_projection:
                geom = project(geom, from_map.crs, to_map.crs)

            for k, v in allocation_mapper[kind](
                geom,
                to_map,
                rtree_index.intersection(geom.bounds),
                meter_projection
            ).items():
                results[(from_index, k)] = v

        except TopologicalError:
            logging.exception("Skipping topological error.")
            continue
        except:
            logging.exception("Intersection worker failed.")
            raise

    return results


class MatchMaker(object):
    @staticmethod
    def get_jobs(map_size):
        # Want a reasonable chunk size
        # But also want a maximum of 200 jobs
        # Both numbers picked more or less at random...
        chunk_size = int(max(20, map_size / 200))
        num_jobs = int(math.ceil(map_size / float(chunk_size)))
        return chunk_size, num_jobs, BetterBar(map_size)

    @classmethod
    def areas(cls, from_map, from_objs=None, cpus=None):
        if from_objs:
            map_size = len(from_objs)
            ids = from_objs
        else:
            map_size = len(Map(from_map))
            ids = range(map_size)

        chunk_size, num_jobs, bar = cls.get_jobs(map_size)

        queue_listener, logging_queue = logger_init()
        logging.info("""Starting MatchMaker `areas` calculation.
        Map: {}
        Map size: {}
        Chunk size: {}
        Number of jobs: {}""".format(
            from_map, map_size, chunk_size, num_jobs
        ))
        results = {}

        def callback_func(data):
            results.update(data)
            bar.update(len(results))

        with multiprocessing.Pool(
                    cpus or multiprocessing.cpu_count(),
                    worker_init,
                    [logging_queue]
                ) as pool:
            arguments = [
                (from_map, chunk, index)
                for index, chunk in enumerate(chunker(ids, chunk_size))
            ]

            function_results = []

            for argument_set in arguments:
                function_results.append(pool.apply_async(
                    areal_calculation,
                    argument_set,
                    callback=callback_func
                ))
            for fr in function_results:
                fr.wait()

            if any(not fr.successful() for fr in function_results):
                raise ValueError("Couldn't complete Pandarus task")

        queue_listener.stop()
        bar.finish()

        logging.info("""Finished MatchMaker `areas` calculation.
        Map: {}
        Map size: {}
        Chunk size: {}
        Number of jobs: {}""".format(
            from_map, map_size, chunk_size, num_jobs
        ))

        return results


    @classmethod
    def intersect(cls, from_map, to_map, from_objs=None, cpus=None):
        if from_objs:
            map_size = len(from_objs)
            ids = from_objs
        else:
            map_size = len(Map(from_map))
            ids = range(map_size)

        chunk_size, num_jobs, bar = cls.get_jobs(map_size)

        queue_listener, logging_queue = logger_init()
        logging.info("""Starting MatchMaker `intersect` calculation.
        From map: {}
        To map: {}
        Map size: {}
        Chunk size: {}
        Number of jobs: {}""".format(
            from_map, to_map, map_size, chunk_size, num_jobs
        ))

        results = {}

        def callback_func(data):
            results.update(data)
            bar.update(len({key[0] for key in results}))

        with multiprocessing.Pool(
                    cpus or multiprocessing.cpu_count(),
                    worker_init,
                    [logging_queue]
                ) as pool:
            arguments = [
                (from_map, chunk, to_map, index)
                for index, chunk in enumerate(chunker(ids, chunk_size))
            ]

            function_results = []

            for argument_set in arguments:
                function_results.append(pool.apply_async(
                    intersection_calculation,
                    argument_set,
                    callback=callback_func
                ))
            for fr in function_results:
                fr.wait()

            if any(not fr.successful() for fr in function_results):
                raise ValueError("Couldn't complete Pandarus task")

        queue_listener.stop()
        bar.finish()

        logging.info("""Finished MatchMaker `intersect` calculation.
        From map: {}
        To map: {}
        Map size: {}
        Chunk size: {}
        Number of jobs: {}""".format(
            from_map, to_map, map_size, chunk_size, num_jobs
        ))

        return results
