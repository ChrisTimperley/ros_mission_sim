import random
import system
import mission
import systemContainer
import threading

"""
A lock is required to mutate the set of containers/ports
"""
manager_lock = threading.Lock()

"""
A registry of systems known to Houston, indexed by their identifiers.
"""
__systems = {}

"""
The pool of ports that are open and available to be used.
"""
__port_pool = set(i for i in range(10000, 10500))

"""
The set of containers that are actively in use.
"""
__containers = set()


def registerSystem(systm):
    """
    Registers a system with Houston.

    @TODO   we could perform this automatically using magic methods / class hooks
    """
    global __systems
    assert (isinstance(systm, system.System) and not systm is None)
    iden = systm.getIdentifier()
    if iden in __systems:
        raise Error("system already registered with name: {}".format(iden))
    __systems[iden] = systm


def setPortRange(start, end):
    """
    Updates the set of ports that are available to Houston. This should not
    be called whilst containers are being provisioned, or missions are being
    executed.
    """
    global __port_pool
    global manager_lock

    assert (isinstance(start, int) and start is not None)
    assert (start >= 1024 and start < 65535)
    assert (isinstance(end, int) and end is not None)
    assert (end >= 1024 and end < 65535)
    assert (start < end)  

    manager_lock.acquire()
    __port_pool = set(i for i in range(start, end))
    manager_lock.release()


def getSystem(identifier):
    """
    Returns the system associated with a given identifier.
    """
    assert (isinstance(identifier, str) or isinstance(identifier, unicode))
    return __systems[identifier]


def destroyContainer(cntr):
    """
    Safely destroys a container by deallocating all attached resources
    (i.e., Docker containers, ports).
    """
    global __port_pool
    global __containers
    global manager_lock

    assert (isinstance(cntr, systemContainer.SystemContainer) and not cntr is None)

    manager_lock.acquire()
    __port_pool.add(cntr.port())
    __containers.remove(cntr)
    cntr.destroy()
    manager_lock.release()


def createContainer(systm, image, verbose=False):
    """
    Constructs a fresh, ephemeral container for a given system using a
    specified Docker image.

    :param  systm:  the System object
    :param  image:  the name of the Docker image that should be used to spawn\
                    the container
    :param  verbose:    a flag indicating whether the outputs of the container \
                        should be printed to the stdout upon its destruction

    :returns    A new SystemContainer for the given system
    """
    global __port_pool
    global __containers
    global manager_lock

    assert (isinstance(systm, system.System))
    assert (not system is None)

    iden = systm.getIdentifier()
    assert (iden in __systems)

    manager_lock.acquire()
    port = random.sample(__port_pool, 1)[0]
    __port_pool.remove(port)

    container = systemContainer.SystemContainer(iden, image, port, verbose=verbose)
    __containers.add(container)
    manager_lock.release()

    return container
