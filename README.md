# Smart-Video-Record-Deepstream-in-Python
Guide to set up DeepStream `pyds` and run an RTSP pipeline in Python.  
**Note:** NVIDIA Smart Recording isn’t in official Python bindings and is supported only in C++. NVIDIA Smart Video Record isn’t in the official Python bindings and is supported only in C++. This guide includes the minimal tweaks to enable Smart Video Recording from Python, and we’ve added a complete example script that shows how to trigger start/stop, handle the sr-done callback, and save clips to disk. We’d love your help making this repo a one-stop place for DeepStream wheels with Smart-Record—if you’ve built a working wheel for your setup, please open a Pull Request so others can use it too!

---

# DeepStream Python Bindings (dspy) — Install & Build
**Ubuntu 22.04 · Python 3.10 · DeepStream 7.1**  
> Python **3.10** is required (3.8 **will not** work).

## Table of Contents
- [Prerequisites](#prerequisites)
  - [DeepStream SDK](#deepstream-sdk)
  - [System Dependencies](#system-dependencies)
  - [PyPA Build Tool](#pypa-build-tool)
- [Clone in the Correct Location](#clone-in-the-correct-location)
- [Initialize Submodules](#initialize-submodules)
- [Build & Install gst-python](#build--install-gst-python)
- [Edit C++ files](#edit-c-files)
- [Additional required fixes](#additional-required-fixed)
- [Edit CMakeLists.txt](#edit-cmakelists-txt)
- [Compiling the bindings](#compiling-the-bindings)
- [Verify](#verify)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### DeepStream SDK
Download and install DeepStream SDK (and dependencies) from:
- https://developer.nvidia.com/deepstream-sdk

After installation, you should have a path like:
~~~bash
/opt/nvidia/deepstream/deepstream-X.X
~~~

**NOTICE THAT** `X.X` **IS YOUR DEEPSTREAM VERSION**, please edit according your version (e.g `7.1`,`8.0`)

### System Dependencies
Install development packages required to build the bindings and gst-python:
~~~bash
sudo apt update
sudo apt install -y \
  python3 python3-pip python3-dev python3.10-dev \
  python3-gi python3-gst-1.0 python-gi-dev \
  git meson ninja-build cmake g++ build-essential \
  libglib2.0-dev libglib2.0-dev-bin libgstreamer1.0-dev \
  libtool m4 autoconf automake \
  libgirepository1.0-dev libcairo2-dev
~~~

### PyPA Build Tool 
Install the PyPA build backend (used to create the wheel):
~~~bash
python3 -m pip install --upgrade pip
python3 -m pip install build
~~~

---

## Clone in the Correct Location
DeepStream expects the Python apps under `sources/`. **NOTICE THAT** `X.X` **IS YOUR DEEPSTREAM VERSION**, please edit according your version (e.g `7.1`,`8.0`)
~~~bash
export DS_ROOT=/opt/nvidia/deepstream/deepstream-X.X
sudo mkdir -p "$DS_ROOT/sources"
sudo chown -R "$USER":"$USER" "$DS_ROOT/sources"

cd "$DS_ROOT/sources"
git clone https://github.com/NVIDIA-AI-IOT/deepstream_python_apps
~~~

You should now have:
~~~bash
/opt/nvidia/deepstream/deepstream-X.X/sources/deepstream_python_apps
~~~

---

## Initialize Submodules
Pull the gst-python and pybind11 submodules:
~~~bash
cd "$DS_ROOT/sources/deepstream_python_apps"
git submodule update --init
python3 bindings/3rdparty/git-partial-submodule/git-partial-submodule.py restore-sparse
~~~

---

## Build & Install gst-python
Build and install `gst-python` so GStreamer’s Python bindings match your build:
~~~bash
cd "$DS_ROOT/sources/deepstream_python_apps/bindings/3rdparty/gstreamer/subprojects/gst-python/"
meson setup build
cd build
ninja
sudo ninja install
~~~

---

## Edit C++ files
Make the following **source additions** to enable Smart Recording–related types and helpers. This files are already ready to use in the folder `bindings`, so you can just replace the files.

### File: `bindings/src/bindfunctions.cpp`
Paste these inside the existing `namespace pydeepstream { ... }` where other `m.def(...)` calls live.
~~~cpp
m.def("set_user_meta_release_callback",
      [](NvDsUserMeta *meta,
         std::function<utils::RELEASEFUNC_SIG> const &func) {
          utils::set_freefunc(meta, func);
      },
      py::call_guard<py::gil_scoped_release>(),
      "meta"_a,
      "func"_a,
      pydsdoc::methodsDoc::user_releasefunc);

m.def("unset_callback_funcs",
      []() { utils::release_all_func(); },
      py::call_guard<py::gil_scoped_release>());

m.def("get_ptr",
      [](size_t ptr) { return (gpointer)ptr; },
      "ptr"_a,
      py::return_value_policy::reference,
      pydsdoc::methodsDoc::get_ptr);

// NEW alias for clarity
m.def("get_native_ptr",
      [](size_t ptr) { return (gpointer)ptr; },
      "ptr"_a,
      py::return_value_policy::reference,
      pydsdoc::methodsDoc::get_ptr);

m.def("strdup",
      [](size_t ptr) -> size_t {
          char *str = (char *)ptr;
          if (!str) return 0;
          char *dup = g_strdup(str);
          return (size_t)dup;
      },
      "ptr"_a,
      pydsdoc::methodsDoc::strdup);
~~~

### File: `bindings/src/utils.cpp`
Add this include near the other DeepStream headers:
~~~cpp
#include "gst-nvdssr.h"
~~~

Then add these bindings (e.g., after the existing `NvDsObjEncUsrArgs` bindings):
~~~cpp
// Enum for Smart Record container type
py::enum_<NvDsSRContainerType>(m, "NvDsSRContainerType")
    .value("NVDSSR_CONTAINER_MP4", NVDSSR_CONTAINER_MP4)
    .value("NVDSSR_CONTAINER_MKV", NVDSSR_CONTAINER_MKV)
    .export_values();

// Smart Record info struct
py::class_<NvDsSRRecordingInfo>(m, "NvDsSRRecordingInfo")
    .def(py::init<>())
    .def_property("filename", STRING_FREE_EXISTING(NvDsSRRecordingInfo, filename))
    .def_property("dirpath",  STRING_FREE_EXISTING(NvDsSRRecordingInfo, dirpath))
    .def_readwrite("duration",       &NvDsSRRecordingInfo::duration)
    .def_readwrite("containerType",  &NvDsSRRecordingInfo::containerType)
    .def_readwrite("width",          &NvDsSRRecordingInfo::width)
    .def_readwrite("height",         &NvDsSRRecordingInfo::height)
    .def_readwrite("containsVideo",  &NvDsSRRecordingInfo::containsVideo)
    .def_readwrite("channels",       &NvDsSRRecordingInfo::channels)
    .def_readwrite("samplingRate",   &NvDsSRRecordingInfo::samplingRate)
    .def_readwrite("containsAudio",  &NvDsSRRecordingInfo::containsAudio)
    .def("cast", [](size_t data) {
            return (NvDsSRRecordingInfo *)data;
         }, py::return_value_policy::reference)
    .def("cast", [](void* data) {
            return (NvDsSRRecordingInfo *)data;
         }, py::return_value_policy::reference);

// Helper for user context in SR callbacks
struct SRUserContext {
    int  sessionid;
    char name[32];
};

py::class_<SRUserContext>(m, "SRUserContext")
    .def(py::init<>())
    .def_readwrite("sessionid", &SRUserContext::sessionid)
    .def_property("name", STRING_CHAR_ARRAY(SRUserContext, name))
    .def("cast", [](size_t data) {
            return (SRUserContext *)data;
         }, py::return_value_policy::reference)
    .def("cast", [](void* data) {
            return (SRUserContext *)data;
         }, py::return_value_policy::reference);
~~~

> Keep all of the above inside `namespace pydeepstream { ... }`.

---
### Additional required fixed
Some builds fail around the `STRING_CHAR_ARRAY` helper used for fixed-size `char[]` fields.
**File:** `bindings/src/utils.hpp` **-- macro for fixed-size** `char[]`
Replace the existing macro with:
```cpp
#ifndef STRING_CHAR_ARRAY
#define STRING_CHAR_ARRAY(Type, member)                                             \
    [](Type &self) -> std::string {                                                 \
        return std::string(self.member);                                            \
    },                                                                              \
    [](Type &self, const std::string &v) {                                          \
        std::snprintf(self.member, sizeof(self.member), "%s", v.c_str());           \
        self.member[sizeof(self.member) - 1] = '\0';                                \
    }
#endif
```cpp
#include <cstdio>   // for std::snprintf
```

---
## Edit CMakeLists txt
Update the build system to target the version  you need e.g. **CMake 3.10**, **Python 3.10**, and (optionally) a versioned DeepStream path.

**Require CMake 3.10 (was 3.12)**
~~~cmake
cmake_minimum_required(VERSION 3.10 FATAL_ERROR)
~~~

**Default Python version: 3.10 (was 3.12)**
~~~cmake
check_variable_set(PYTHON_MAJOR_VERSION 3)
check_variable_set(PYTHON_MINOR_VERSION 10)
~~~

**Allowed Python minor version: 10 (was 12)**
~~~cmake
set(PYTHON_MINVERS_ALLOWED 10)
check_variable_allowed(PYTHON_MINOR_VERSION PYTHON_MINVERS_ALLOWED)
~~~

**Versioned DeepStream path (replace `X.X`, e.g., `7.1`)**
~~~cmake
check_variable_set(DS_PATH "/opt/nvidia/deepstream/deepstream-X.X")
~~~
*(Optional generic form)*
~~~cmake
check_variable_set(DS_VERSION "7.1")
check_variable_set(DS_PATH "/opt/nvidia/deepstream/deepstream-${DS_VERSION}")
~~~

---

## Compiling the bindings
> Output: a Python wheel under `bindings/dist/` that you can install with `pip`.

### x86 (Ubuntu 22.04 · Python 3.10 · DeepStream 7.1)
~~~bash
cd "$DS_ROOT/sources/deepstream_python_apps/bindings"
export CMAKE_BUILD_PARALLEL_LEVEL=$(nproc)
python3 -m build
cd dist
python3 -m pip install --force-reinstall *.whl
~~~

### Jetson (Ubuntu 22.04 · Python 3.10 · DeepStream 7.1)
~~~bash
cd "$DS_ROOT/sources/deepstream_python_apps/bindings"
export CMAKE_BUILD_PARALLEL_LEVEL=$(nproc)
python3 -m build
cd dist
python3 -m pip install --force-reinstall *.whl
~~~

### SBSA (Ubuntu 22.04 · Python 3.10 · DeepStream 7.1)
~~~bash
cd "$DS_ROOT/sources/deepstream_python_apps/bindings"
export CMAKE_ARGS="-DIS_SBSA=on"
export CMAKE_BUILD_PARALLEL_LEVEL=$(nproc)
python3 -m build
cd dist
python3 -m pip install --force-reinstall *.whl
~~~

---

## Verify
~~~bash
python3 - <<'PY'
import gi
gi.require_version("Gst","1.0")
from gi.repository import Gst
Gst.init(None)

import pyds
print("Gst OK, pyds OK")

# new alias should exist
assert hasattr(pyds, "get_native_ptr")
print("get_native_ptr OK")
PY
~~~

---

## Troubleshooting
- **Python version mismatch**: `python3 --version` must be **3.10.x**. Use `python3.10` explicitly if needed.
- **Missing Ninja**: Ensure `ninja-build` is installed.
- **DeepStream path**: If you changed `DS_PATH`, confirm headers/libs exist under that folder.
- **GStreamer/GLib headers**: Install `libgstreamer1.0-dev` and `libglib2.0-dev`.
- **Clean rebuild**:
  ~~~bash
  cd "$DS_ROOT/sources/deepstream_python_apps/bindings"
  git clean -fdX build dist *.egg-info
  export CMAKE_BUILD_PARALLEL_LEVEL=$(nproc)
  python3 -m build
  cd dist && python3 -m pip install --force-reinstall *.whl
  ~~~

---

### Contribute Your Prebuilt Wheels

We’d love your help making this repo a one-stop place for DeepStream wheels.  
If you’ve successfully built a wheel that works on your setup, please open a Pull Request and add it so others can use it too!

## What to contribute
- **Wheel file** (`.whl`) built for a specific stack (DeepStream/JetPack/Ubuntu), architecture, and Python version.
- **Checksums**: a `SHA256SUMS.txt` in the same folder as the wheel, and (if possible) update the root `SHA256SUMS.txt`.
- *(Optional)* **Constraints file** if special pins are needed (e.g., `numpy==1.26.0`).

## Folder layout (must follow this)
```shell
wheels/<package>/<version>/
└── DS-<DS_MAJOR.MINOR>_JP<JP_MAJOR.MINOR>_UBU<UBUNTU_MAJOR.MINOR>/
    └── <arch>/
        └── cp<PYMAJMIN>/
            ├── <original-wheel-name>.whl
            └── SHA256SUMS.txt
```

**Notes**
- `arch` is `linux_x86_64` (PC) or `aarch64` (Jetson).
- `cp312` = Python 3.12; `cp310` = Python 3.10, etc.
- Keep the **original wheel filename** intact.

## Include compatibility info in your PR
- DeepStream version (e.g., `DS 8.0` or `DS 7.1`)
- JetPack & Ubuntu (e.g., `JP 6.1 / Ubuntu 22.04`)
- Python version (e.g., `3.12`)
- Architecture (`x86_64` or `aarch64`)
- Any special constraints (e.g., `numpy==1.26.0`)


## Quick PR checklist
- Wheel placed in the correct folder structure.
- Short compatibility section in the PR description.

Thanks for sharing your builds—your contribution helps the whole community install reliably without rebuilding! 🙌



