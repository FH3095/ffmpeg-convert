#!/usr/bin/env python3

from collections import namedtuple
from threading import RLock
import codecs,sys,configparser,subprocess,pathlib,logging,shutil,concurrent.futures

def getUserOptions(config):
    preset = None
    #sys.argv = sys.argv + ["AudioOpus", "n"] ## DEBUG FIXME
    if len(sys.argv) > 1:
        preset = sys.argv[1]
    else:
        print("Configured presets:", ' '.join(config.sections()))
        preset = input("Which preset? ")
    if not preset in config:
        print("Invalid preset", preset, "Valid presets are", config.sections(), file=sys.stderr)
        sys.exit(1)

    if config[preset]["MetadataConvert"].lower() == "yes":
        return preset, True
    elif config[preset]["MetadataConvert"].lower() == "no":
        return preset, False

    if len(sys.argv) == 2: # Preset is set to ask, preset is also set via cmdline but metadata-answer is not set via cmdline
        print("Chosen preset", preset, "has MetadataConvert set to ask but cmdline-parameter is not given", file=sys.stderr)
        print("Use", sys.argv[0], "<Preset> <y/n>", file=sys.stderr)
        sys.exit(1)

    removeAllMetadata = None
    if len(sys.argv) > 2:
        removeAllMetadata = sys.argv[2].lower() == "y"
    else:
        removeAllMetadata = input("Remove all metadata? ").lower() == "y"

    return preset, removeAllMetadata


def runProcess(cmdLine, cwd):
    result = subprocess.run(cmdLine, cwd=cwd, check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, shell=True)
    with outputLock:
        log.info("Finished %s. Result: %i %s", cmdLine, result.returncode, result.stdout)
    result.check_returncode()


def convertVideoFile(formatConfig, inputFile, tmpFile):
    cmd = formatConfig["FFmpegPath"] + " " + formatConfig["PrependToCmd"] + " " + formatConfig["Cmd"] + " "
    cmd = cmd + formatConfig["AppendToCmd"] + " \"{TEMP_FILE}\""
    cmd = cmd.format(FFMPEG_PATH=formatConfig["FFmpegPath"], INPUT_FILE=inputFile, TEMP_FILE=tmpFile, TEMP_BASE=tmpFile.with_suffix(""))
    runProcess(cmd, tmpFile.parent)


def extractMetadata(formatConfig, inputFile, metadataFile):
    cmd = formatConfig["FFmpegPath"] + " " + formatConfig["MetadataExtract"]
    cmd = cmd.format(FFMPEG_PATH=formatConfig["FFmpegPath"], INPUT_FILE=inputFile, METADATA_FILE=metadataFile)
    runProcess(cmd, metadataFile.parent)
    allowedMetaTags = ["#", ";"] + formatConfig["MetadataCopy"].split()
    metaOut = []
    with codecs.open(metadataFile, "r", "utf-8") as metaFile:
        for line in metaFile:
            for tag in allowedMetaTags:
                if line.startswith(tag):
                    metaOut.append(line)
    with codecs.open(metadataFile, "w", "utf-8") as metaFile:
        metaFile.writelines(metaOut)


def insertMetadata(formatConfig, tmpFile, metadataFile, outputFile):
    cmd = formatConfig["FFmpegPath"] + " " + formatConfig["MetadataInsert"]
    cmd = cmd.format(FFMPEG_PATH=formatConfig["FFmpegPath"], TEMP_FILE=tmpFile, METADATA_FILE=metadataFile, OUTPUT_FILE=outputFile)
    runProcess(cmd, tmpFile.parent)


ConvertEntry = namedtuple("ConvertEntry", ["relativeFile", "inFile", "tmpFile", "metadataFile", "outFile"])

def convertOneFile(formatConfig, removeAllMetadata, entry):
    with outputLock:
        print("Converting", entry.relativeFile)
    entry.tmpFile.parent.mkdir(parents=True, exist_ok=True)
    entry.outFile.parent.mkdir(parents=True, exist_ok=True)
    if not removeAllMetadata:
        extractMetadata(formatConfig, entry.inFile, entry.metadataFile)
    convertVideoFile(formatConfig, entry.inFile, entry.tmpFile)
    if not removeAllMetadata:
        insertMetadata(formatConfig, entry.tmpFile, entry.metadataFile, entry.outFile)
    else:
        shutil.copy(entry.tmpFile, entry.outFile)


def convertAllFiles(formatConfig, removeAllMetaData):
    inDir = pathlib.Path(formatConfig["InDir"]).absolute()
    tmpDir = pathlib.Path(formatConfig["TmpDir"]).absolute()
    outDir = pathlib.Path(formatConfig["OutDir"]).absolute()
    print("Searching all files in", inDir, "and writing converted files to", outDir)
    entries = list()
    for file in inDir.glob("**/*.*"):
        relativeFile = file.relative_to(inDir)
        tmpFile = tmpDir.joinpath(relativeFile).with_suffix("."+formatConfig["FileEnding"])
        metadataFile = tmpDir.joinpath(relativeFile).with_suffix(".txt")
        outFile = outDir.joinpath(relativeFile).with_suffix("."+formatConfig["FileEnding"])
        entries.append(ConvertEntry(relativeFile, file, tmpFile, metadataFile, outFile))
    entries = tuple(sorted(entries))
    with concurrent.futures.ThreadPoolExecutor(max_workers=int(formatConfig["FFmpegInstances"])) as executor:
        jobs = list()
        for entry in entries:
            jobs.append(executor.submit(convertOneFile, formatConfig, removeAllMetadata, entry))
        for job in jobs:
            job.result()
    print("Done converting, cleaning up tmp")
    for child in tmpDir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()



outputLock = RLock()

config = configparser.ConfigParser()
with codecs.open("settings.ini", "r", "utf-8") as configFile:
    config.read_file(configFile)

logging.basicConfig(filename=config["DEFAULT"]["Log"], level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging

preset, removeAllMetadata = getUserOptions(config)
convertAllFiles(config[preset], removeAllMetadata)

