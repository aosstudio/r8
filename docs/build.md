# Build R8

The build runs on Linux x86-64 with glibc and requires Python 3.12 or newer, GNU Make, Bash, curl, tar and flock. It downloads the pinned AOSStudio JDK 21 asset from [GitHub Releases](https://github.com/aosstudio/jdk/releases/tag/latest). The build and verification both use that JDK.

```sh
make build
make verify
```

The first build fetches and verifies the inputs in [the lock file](../locks/inputs.json). `make fetch` populates the cache separately. The R8 source commits, dependencies, compiler tools and JDK archive are pinned. The JDK nightly URL is mutable. If GitHub replaces that asset and its digest changes, review the new release before updating the pin.

Both builds compile the Java and Kotlin sources and generate Java bindings from upstream Protobuf schemas. The API database is copied byte for byte from the independently licensed upstream R8 Maven artifact. The R8 classes in that Maven artifact are outside the build classpath. R8 source resources, licenses and dependency notices are retained.

| Output under `out/dist/` | Use |
| --- | --- |
| `aosstudio-r8-9.5.28.tar.gz` | Standalone D8, R8 and Retrace launchers with their runtime JARs for SDK tools |
| `aosstudio-r8-9.5.29-agp.jar` | Relocated R8 library for AGP 9.5.2. AGP supplies its Android tools dependencies. |

The verification checks the packaged API database and exercises D8, R8 and Retrace in both packages. For static checks, install ShellCheck and the Python lint dependencies listed in `ci/lint-requirements.txt` and run `make check`. The pinned lint wheels target Linux x86-64 and CPython 3.14.
