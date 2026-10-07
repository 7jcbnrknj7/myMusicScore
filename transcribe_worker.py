"""Run the upstream CLI with a longer, bounded engraving timeout."""
import runpy

from muscriptor.utils import sheets
from notation import native_tablature_parts, retain_tab_instruments

original_tab_conversion = sheets.convert_to_tab_staves


def convert_supported_tabs(path):
    retain_tab_instruments(path,native_tablature_parts(path))
    return original_tab_conversion(path)


sheets.fretted_parts = native_tablature_parts
sheets.convert_to_tab_staves = convert_supported_tabs

sheets.RUN_TIMEOUT_S = 600
runpy.run_module('muscriptor', run_name='__main__')
