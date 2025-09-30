from setuptools import setup

APP = ['src/app.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'plist': {
        'CFBundleName': 'Ki-Porter',
        'CFBundleIdentifier': 'com.vanguard.ki-porter',
        'CFBundleVersion': '1.0',
        'LSMinimumSystemVersion': '10.15',
        # This tells macOS your app owns/opens these extensions:
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'KiCad Symbol',
                'CFBundleTypeRole': 'Viewer',
                'LSHandlerRank': 'Alternate',
                'CFBundleTypeExtensions': ['kicad_sym'],
            },
            {
                'CFBundleTypeName': 'KiCad Footprint',
                'CFBundleTypeRole': 'Viewer',
                'LSHandlerRank': 'Alternate',
                'CFBundleTypeExtensions': ['kicad_mod'],
            },
            {
                'CFBundleTypeName': 'KiCad 3D Model',
                'CFBundleTypeRole': 'Viewer',
                'LSHandlerRank': 'Alternate',
                'CFBundleTypeExtensions': ['step', 'wrl'],
            },
        ],
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)