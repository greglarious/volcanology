from setuptools import setup, find_packages
 
setup(
    name = "volcanology",
    description = "scans jenkins job status and activates various indicators",
    author = "greglarious",
    author_email = "greglarious@gmail.com",
    url = "https://github.com/greglarious/volcanology",
    version = "0.1",
    packages = find_packages(),
    install_requires=["holidays"],
    scripts=["start_volcanology.sh"],
)
