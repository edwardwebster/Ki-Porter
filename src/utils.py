import os

def find(path, name):
    r"""! \brief Locate a directory by name within a hierarchy.

    \param path Root directory to walk.
    \param name Target directory name to locate.
    \return Absolute path to the first matching directory or ``None``.
    """
    for root, dirs, files in os.walk(path):
        if name in dirs:
            return os.path.join(root, name)
    return None
