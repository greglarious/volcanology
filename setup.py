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
    data_files=[
      ('config', ['config/volcanology.ini', 'config/logging_config.ini']),
      ('bin', ['start_volcanology.sh']),
    ],
)
