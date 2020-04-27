# syncopath - Synchronize the contents of one directory to another.
# Copyright (C) 2017-2020 Kurt McKee <contactme@kurtmckee.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging
import os
import queue
import stat
import threading

from .__version__ import __version__

_listdir = os.listdir
_scandir = os.scandir
_stat = os.stat

__all__ = ['sync']


log = logging.getLogger(__name__)

# When reading files across the network, this will be the size of each chunk.
BUFFER_SIZE = 128 * 1024  # 128KB

# The thread manager ensures that only a certain number of threads exist
# at any given moment. This prevents runaway thread creation.
count = 4
thread_manager = threading.Semaphore(count)
io_queue = queue.Queue(count)

_isdir = stat.S_ISDIR
_isreg = stat.S_ISREG
_join = os.path.join
_normpath = os.path.normpath
_normcase = os.path.normcase
_remove = os.remove
_st_atime = stat.ST_ATIME
_st_mode = stat.ST_MODE
_st_mtime = stat.ST_MTIME
_st_size = stat.ST_SIZE
_Thread = threading.Thread


def sync(left, right):
    plans = plan(left, right)
    execute(left, right, plans)


def plan(left, right):
    left = _normcase(_normpath(left))
    right = _normcase(_normpath(right))

    results = queue.Queue()
    directories = queue.Queue()
    directories.put('')
    consolidated_results = queue.Queue()
    consolidated_results.put({
        'rmdir': set(),
        'rmfile': set(),
        'rmlink': set(),
        'mkdir': set(),
        'copy': set(),
    })

    # Launch _consolidate_results in a thread.
    args = (results, consolidated_results)
    plan_thread = _Thread(target=_consolidate_results, args=args)
    plan_thread.start()

    # Launch _compare in a thread.
    args = (left, right, directories, results)
    compare_thread = _Thread(target=_compare, args=args)
    compare_thread.start()

    # Wait for all directories to be compared, then force the _compare thread
    # to exit gracefully.
    directories.join()
    directories.put(None)
    compare_thread.join()

    # Wait for all results to be consolidated, then force the
    # _consolidate_results thread to exit gracefully.
    results.join()
    results.put(None)
    plan_thread.join()

    # Get the final plans.
    plans = consolidated_results.get()
    consolidated_results.task_done()
    consolidated_results.join()

    return plans


def execute(left, right, plans):
    log.debug('Executing from "{}" to "{}"'.format(left, right))
    log.debug('Using buffer size: {}'.format(BUFFER_SIZE))

    # Ensure the right side exists.
    if not os.path.exists(right):
        os.makedirs(right)

    # Remove files on the right side.
    for filename in plans['rmfile']:
        thread_manager.acquire()
        io_queue.put(None)
        thread = _Thread(target=unlink, args=(_join(right, filename),))
        thread.start()

    io_queue.join()

    # Remove directories on the right side.
    for directory in sorted(plans['rmdir'], reverse=True):
        os.rmdir(_join(right, directory))

    # Make new directories on the right side.
    for directory in sorted(plans['mkdir']):
        os.makedirs(_join(right, directory))

    # Copy files from the left side to the right side.
    for path, stats in sorted(plans['copy'], key=lambda x: x[1][_st_size], reverse=True):
        thread_manager.acquire()
        io_queue.put(None)
        thread = _Thread(target=copy, args=(left, right, path, stats))
        thread.start()

    io_queue.join()


def listdir(results, path):
    try:
        results.put(list(_scandir(path)))
    except OSError:
        results.put([])


def _consolidate_results(results, consolidated_results):
    """
    :type results: queue.Queue
    :type consolidated_results: queue.Queue
    """

    plans = consolidated_results.get()

    while 1:
        result = results.get()
        if result is None:
            break

        for k, v in result.items():
            plans[k].update(v)
        results.task_done()

    consolidated_results.put(plans)
    consolidated_results.task_done()


def _compare(left, right, directories, results):
    """
    :type left: str
    :type right: str
    :type directories: queue.Queue
    :type results: queue.Queue
    :return:
    """

    while 1:
        relative_directory = directories.get()
        if relative_directory is None:
            break

        args = (left, right, relative_directory, directories, results)
        thread_manager.acquire()
        thread = _Thread(target=_compare_directory, args=args)
        thread.start()


def _compare_directory(left, right, relative_path, directories, results):
    """
    :type left: str
    :type right: str
    :type relative_path: str
    :type directories: queue.Queue
    :type results: queue.Queue
    """

    plans = {
        'rmdir': set(),
        'rmfile': set(),
        'rmlink': set(),
        'mkdir': set(),
        'copy': set(),
    }

    left_path = _join(left, relative_path)
    left_result = queue.Queue(maxsize=1)
    left_thread = _Thread(target=listdir, args=(left_result, left_path))
    left_thread.start()

    right_path = _join(right, relative_path)
    right_result = queue.Queue(maxsize=1)
    right_thread = _Thread(target=listdir, args=(right_result, right_path))
    right_thread.start()

    left_thread.join()
    right_thread.join()

    # scandir.DirEntry supports hashing but not equality comparisons
    # so we must use the .name attribute for equality comparisons.
    left_listing = {_normcase(i.name): i for i in left_result.get()}
    left_result.task_done()
    left_result.join()
    right_listing = {_normcase(i.name): i for i in right_result.get()}
    right_result.task_done()
    right_result.join()

    # Case 1: The file/directory only exists on the left.
    for name in left_listing.keys() - right_listing.keys():
        left_path = _join(relative_path, left_listing[name].name)
        if left_listing[name].is_dir():
            directories.put(left_path)
            plans['mkdir'].add(left_path)
        else:
            # stat() the file in a separate thread.
            thread = _Thread(target=left_listing[name].stat)
            thread.start()
            thread.join()

            # The stat() call below was cached above by scandir.DirEntry.
            left_stat = left_listing[name].stat()
            plans['copy'].add((left_path, left_stat))

    # Case 2: The file/directory only exists on the right.
    for name in right_listing.keys() - left_listing.keys():
        right_path = _join(relative_path, right_listing[name].name)
        if right_listing[name].is_dir():
            directories.put(right_path)
            plans['rmdir'].add(right_path)
        else:
            plans['rmfile'].add(right_path)

    # Case 3: The path exists on both the left and right sides.
    for name in left_listing.keys() & right_listing.keys():
        left_path = _join(relative_path, left_listing[name].name)
        right_path = _join(relative_path, right_listing[name].name)

        # Case 3.1: The left side is a directory.
        if left_listing[name].is_dir():
            directories.put(left_path)
            # If the right side is a file it must be removed.
            if right_listing[name].is_file():
                plans['rmfile'].add(right_path)

        # Case 3.2: The left side is a file.
        elif left_listing[name].is_file():
            # stat() the file in a separate thread.
            thread = _Thread(target=left_listing[name].stat)
            thread.start()
            thread.join()

            # The stat() call below was cached above by scandir.DirEntry.
            left_stat = left_listing[name].stat()

            # If the right side is a directory, it must be recursively removed
            # and the file on the left side must be copied to the right side.
            if right_listing[name].is_dir():
                directories.put(right_path)
                plans['rmdir'].add(right_path)
                plans['copy'].add((left_path, left_stat))

            # If the right side is a file, its size and attributes must match
            # the size and attributes of the file on the left side.
            elif right_listing[name].is_file():
                thread = _Thread(target=right_listing[name].stat)
                thread.start()
                thread.join()

                # The stat() call below was cached above by scandir.DirEntry.
                right_stat = right_listing[name].stat()

                # If the file sizes differ, copy the file.
                if left_stat[_st_size] != right_stat[_st_size]:
                    plans['copy'].add((left_path, left_stat))
                # If the file modification times differ, copy the file.
                if left_stat[_st_mtime] != right_stat[_st_mtime]:
                    plans['copy'].add((left_path, left_stat))

    results.put(plans)
    directories.task_done()
    thread_manager.release()


def unlink(path):
    """
    :type path: str
    """

    os.unlink(path)
    thread_manager.release()
    io_queue.get()
    io_queue.task_done()


def copy(left, right, path, stats):
    """
    :type left: str
    :type right: str
    :type path: str
    :type stats: list
    """

    blobs = queue.Queue(8)

    # Open the left and right files.
    reader_queue = queue.Queue(maxsize=1)
    get_reader_thread = _Thread(target=open_file, args=[_join(left, path), 'rb', reader_queue])
    get_reader_thread.start()
    writer_queue = queue.Queue(maxsize=1)
    get_writer_thread = _Thread(target=open_file, args=[_join(right, path), 'wb', writer_queue])
    get_writer_thread.start()
    src = reader_queue.get()
    dst = writer_queue.get()

    # If both files were opened successfully, copy the contents.
    if src and dst:
        # Launch a thread for reading.
        read_thread = _Thread(target=read, args=(src, blobs))
        read_thread.start()

        # Launch a thread for writing.
        write_thread = _Thread(target=write, args=(dst, blobs))
        write_thread.start()

        read_thread.join()
        write_thread.join()

        src.close()
        dst.close()

        # Update the access and modification times.
        os.utime(_join(right, path), (stats[_st_atime], stats[_st_mtime]))

    # If only one file was successfully opened, be sure to close it.
    if src:
        src.close()
    if dst:
        dst.close()

    thread_manager.release()
    io_queue.get()
    io_queue.task_done()


def read(src, blobs, size=BUFFER_SIZE):
    try:
        while 1:
            blob = src.read(size)
            if not blob:
                break
            blobs.put(blob)
    except IOError as error:
        log.debug('{}: {}'.format(error.__class__.__name__, error))
    finally:
        src.close()

    blobs.put(None)


def write(dst, blobs):
    try:
        while 1:
            blob = blobs.get()
            if blob is None:
                break
            dst.write(blob)
            blobs.task_done()
    except IOError as error:
        log.debug('{}: {}'.format(error.__class__.__name__, error))

        # If there's an error, the queue still needs to get cleared.
        # Eventually it will be important to kill the reader thread
        # instead of letting it just keep reading.
        while 1:
            blob = blobs.get()
            if blob is None:
                break
    finally:
        dst.close()


def open_file(path, mode, pipe):
    """Open a path for reading or writing.

    The file object will be put into the queue if the file is successfully
    opened. If there is an exception it will be put into the pipe instead.

    The file will need to be closed later.

    :param str path: The path to the file.
    :param str mode: The mode to open the file with.
    :param queue.Queue pipe: The open file or an error will be put in the pipe.
    """

    try:
        pipe.put(open(path, mode))
    except IOError as error:
        log.debug('{}: {}'.format(error.__class__.__name__, str(error)))
        pipe.put(None)
