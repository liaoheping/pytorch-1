from setuptools import setup, Extension, distutils, Command, find_packages
import setuptools.command.build_ext
import setuptools.command.install
import distutils.command.build
import distutils.command.clean
import platform
import subprocess
import shutil
import sys
import os

from tools.setup_helpers.env import check_env_flag
from tools.setup_helpers.cuda import WITH_CUDA, CUDA_HOME
from tools.setup_helpers.cudnn import WITH_CUDNN, CUDNN_LIB_DIR, CUDNN_INCLUDE_DIR
DEBUG = check_env_flag('DEBUG')

################################################################################
# Monkey-patch setuptools to compile in parallel
################################################################################

def parallelCCompile(self, sources, output_dir=None, macros=None, include_dirs=None, debug=0, extra_preargs=None, extra_postargs=None, depends=None):
    # those lines are copied from distutils.ccompiler.CCompiler directly
    macros, objects, extra_postargs, pp_opts, build = self._setup_compile(output_dir, macros, include_dirs, sources, depends, extra_postargs)
    cc_args = self._get_cc_args(pp_opts, debug, extra_preargs)

    # compile using a thread pool
    import multiprocessing.pool
    def _single_compile(obj):
        src, ext = build[obj]
        self._compile(obj, src, ext, cc_args, extra_postargs, pp_opts)
    num_jobs = multiprocessing.cpu_count()
    multiprocessing.pool.ThreadPool(num_jobs).map(_single_compile, objects)

    return objects

distutils.ccompiler.CCompiler.compile = parallelCCompile

################################################################################
# Custom build commands
################################################################################

class build_deps(Command):
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        from tools.nnwrap import generate_wrappers as generate_nn_wrappers
        build_all_cmd = ['bash', 'torch/lib/build_all.sh']
        if WITH_CUDA:
            build_all_cmd += ['--with-cuda']
        if subprocess.call(build_all_cmd) != 0:
            sys.exit(1)
        generate_nn_wrappers()


class build_module(Command):
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        self.run_command('build_py')
        self.run_command('build_ext')


class build_ext(setuptools.command.build_ext.build_ext):
    def run(self):
        # Print build options
        if WITH_NUMPY:
            print('-- Building with NumPy bindings')
        else:
            print('-- NumPy not found')
        if WITH_CUDNN:
            print('-- Detected cuDNN at ' + CUDNN_LIB_DIR + ', ' + CUDNN_INCLUDE_DIR)
        else:
            print('-- Not using cuDNN')
        if WITH_CUDA:
            print('-- Detected CUDA at ' + CUDA_HOME)
        else:
            print('-- Not using CUDA')

        # cwrap depends on pyyaml, so we can't import it earlier
        from tools.cwrap import cwrap
        from tools.cwrap.plugins.THPPlugin import THPPlugin
        from tools.cwrap.plugins.ArgcountSortPlugin import ArgcountSortPlugin
        from tools.cwrap.plugins.AutoGPU import AutoGPU
        from tools.cwrap.plugins.BoolOption import BoolOption
        from tools.cwrap.plugins.KwargsPlugin import KwargsPlugin
        from tools.cwrap.plugins.NullableArguments import NullableArguments
        from tools.cwrap.plugins.CuDNNPlugin import CuDNNPlugin
        thp_plugin = THPPlugin()
        cwrap('torch/csrc/generic/TensorMethods.cwrap', plugins=[
            BoolOption(), thp_plugin, AutoGPU(condition='IS_CUDA'),
            ArgcountSortPlugin(), KwargsPlugin()
        ])
        cwrap('torch/csrc/cudnn/cuDNN.cwrap', plugins=[
            CuDNNPlugin(), NullableArguments()
        ])
        # It's an old-style class in Python 2.7...
        setuptools.command.build_ext.build_ext.run(self)


class build(distutils.command.build.build):
    sub_commands = [
        ('build_deps', lambda self: True),
    ] + distutils.command.build.build.sub_commands


class install(setuptools.command.install.install):
    def run(self):
        if not self.skip_build:
            self.run_command('build_deps')
        setuptools.command.install.install.run(self)


class clean(distutils.command.clean.clean):
    def run(self):
        import glob
        with open('.gitignore', 'r') as f:
            ignores = f.read()
            for wildcard in filter(bool, ignores.split('\n')):
                for filename in glob.glob(wildcard):
                    try:
                        os.remove(filename)
                    except OSError:
                        shutil.rmtree(filename, ignore_errors=True)

        # It's an old-style class in Python 2.7...
        distutils.command.clean.clean.run(self)



################################################################################
# Configure compile flags
################################################################################

include_dirs = []
extra_link_args = []
extra_compile_args = ['-std=c++11', '-Wno-write-strings']
if os.getenv('PYTORCH_BINARY_BUILD') and platform.system() == 'Linux':
    print('PYTORCH_BINARY_BUILD found. Static linking libstdc++ on Linux')
    extra_compile_args += ['-static-libstdc++']
    extra_link_args += ['-static-libstdc++']

cwd = os.path.dirname(os.path.abspath(__file__))
lib_path = os.path.join(cwd, "torch", "lib")

tmp_install_path = lib_path + "/tmp_install"
include_dirs += [
    cwd,
    os.path.join(cwd, "torch", "csrc"),
    tmp_install_path + "/include",
    tmp_install_path + "/include/TH",
]

extra_link_args.append('-L' + lib_path)

# we specify exact lib names to avoid conflict with lua-torch installs
TH_LIB     = os.path.join(lib_path, 'libTH.so.1')
THS_LIB    = os.path.join(lib_path, 'libTHS.so.1')
THC_LIB    = os.path.join(lib_path, 'libTHC.so.1')
THCS_LIB    = os.path.join(lib_path, 'libTHCS.so.1')
THNN_LIB   = os.path.join(lib_path, 'libTHNN.so.1')
THCUNN_LIB = os.path.join(lib_path, 'libTHCUNN.so.1')
if platform.system() == 'Darwin':
    TH_LIB     = os.path.join(lib_path, 'libTH.1.dylib')
    THS_LIB    = os.path.join(lib_path, 'libTHS.1.dylib')
    THC_LIB    = os.path.join(lib_path, 'libTHC.1.dylib')
    THCS_LIB   = os.path.join(lib_path, 'libTHCS.1.dylib')
    THNN_LIB   = os.path.join(lib_path, 'libTHNN.1.dylib')
    THCUNN_LIB = os.path.join(lib_path, 'libTHCUNN.1.dylib')

main_compile_args = ['-D_THP_CORE']
main_libraries = ['shm']
main_link_args = [TH_LIB, THS_LIB]
main_sources = [
    "torch/csrc/Module.cpp",
    "torch/csrc/Generator.cpp",
    "torch/csrc/Size.cpp",
    "torch/csrc/Exceptions.cpp",
    "torch/csrc/Tensor.cpp",
    "torch/csrc/Storage.cpp",
    "torch/csrc/byte_order.cpp",
    "torch/csrc/utils.cpp",
    "torch/csrc/allocators.cpp",
    "torch/csrc/serialization.cpp",
    "torch/csrc/autograd/init.cpp",
    "torch/csrc/autograd/variable.cpp",
    "torch/csrc/autograd/function.cpp",
    "torch/csrc/autograd/engine.cpp",
]

try:
    import numpy as np
    include_dirs += [np.get_include()]
    extra_compile_args += ['-DWITH_NUMPY']
    WITH_NUMPY = True
except ImportError:
    WITH_NUMPY = False

if WITH_CUDA:
    cuda_lib_dirs = ['lib64', 'lib']
    cuda_include_path = os.path.join(CUDA_HOME, 'include')
    for lib_dir in cuda_lib_dirs:
        cuda_lib_path = os.path.join(CUDA_HOME, lib_dir)
        if os.path.exists(cuda_lib_path):
            break
    include_dirs.append(cuda_include_path)
    extra_link_args.append('-L' + cuda_lib_path)
    extra_link_args.append('-Wl,-rpath,' + cuda_lib_path)
    extra_compile_args += ['-DWITH_CUDA']
    extra_compile_args += ['-DCUDA_LIB_PATH=' + cuda_lib_path]
    main_link_args += [THC_LIB, THCS_LIB]
    main_sources += [
        "torch/csrc/cuda/Module.cpp",
        "torch/csrc/cuda/Storage.cpp",
        "torch/csrc/cuda/Stream.cpp",
        "torch/csrc/cuda/Tensor.cpp",
        "torch/csrc/cuda/AutoGPU.cpp",
        "torch/csrc/cuda/utils.cpp",
        "torch/csrc/cuda/serialization.cpp",
    ]

if WITH_CUDNN:
    main_libraries += ['cudnn']
    include_dirs.append(CUDNN_INCLUDE_DIR)
    extra_link_args.append('-L' + CUDNN_LIB_DIR)
    main_sources += [
        "torch/csrc/cudnn/Module.cpp",
        "torch/csrc/cudnn/BatchNorm.cpp",
        "torch/csrc/cudnn/Conv.cpp",
        "torch/csrc/cudnn/cuDNN.cpp",
        "torch/csrc/cudnn/Types.cpp",
        "torch/csrc/cudnn/Handles.cpp",
        "torch/csrc/cudnn/CppWrapper.cpp",
    ]
    extra_compile_args += ['-DWITH_CUDNN']

if DEBUG:
    extra_compile_args += ['-O0', '-g']
    extra_link_args += ['-O0', '-g']


def make_relative_rpath(path):
    if platform.system() == 'Darwin':
        return '-Wl,-rpath,@loader_path/' + path
    else:
        return '-Wl,-rpath,$ORIGIN/' + path

################################################################################
# Declare extensions and package
################################################################################

extensions = []
packages = find_packages(exclude=('tools.*',))

C = Extension("torch._C",
    libraries=main_libraries,
    sources=main_sources,
    language='c++',
    extra_compile_args=main_compile_args + extra_compile_args,
    include_dirs=include_dirs,
    extra_link_args=extra_link_args + main_link_args + [make_relative_rpath('lib')],
)
extensions.append(C)

DL = Extension("torch._dl",
    sources=["torch/csrc/dl.c"],
    language='c',
)
extensions.append(DL)

THNN = Extension("torch._thnn._THNN",
    sources=['torch/csrc/nn/THNN.cpp'],
    language='c++',
    extra_compile_args=extra_compile_args,
    include_dirs=include_dirs,
    extra_link_args=extra_link_args + [
        TH_LIB,
        THNN_LIB,
        make_relative_rpath('../lib'),
    ]
)
extensions.append(THNN)

if WITH_CUDA:
    THCUNN = Extension("torch._thnn._THCUNN",
        sources=['torch/csrc/nn/THCUNN.cpp'],
        language='c++',
        extra_compile_args=extra_compile_args,
        include_dirs=include_dirs,
        extra_link_args=extra_link_args + [
            TH_LIB,
            THC_LIB,
            THCUNN_LIB,
            make_relative_rpath('../lib'),
        ]
    )
    extensions.append(THCUNN)

version="0.1"
if os.getenv('PYTORCH_BUILD_VERSION'):
    version = os.getenv('PYTORCH_BUILD_VERSION') \
              + '_' + os.getenv('PYTORCH_BUILD_NUMBER')

setup(name="torch", version=version,
    ext_modules=extensions,
    cmdclass = {
        'build': build,
        'build_ext': build_ext,
        'build_deps': build_deps,
        'build_module': build_module,
        'install': install,
        'clean': clean,
    },
    packages=packages,
    package_data={'torch': [
        'lib/*.so*', 'lib/*.dylib*',
        'lib/torch_shm_manager',
        'lib/*.h',
        'lib/include/TH/*.h', 'lib/include/TH/generic/*.h',
        'lib/include/THC/*.h', 'lib/include/THC/generic/*.h']},
    install_requires=['pyyaml'],
)
