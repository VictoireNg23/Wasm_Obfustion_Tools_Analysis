from importlib import reload

from strategies import state
# reload(state)
import math
import random
import re
from wasmParser.parser import retIndent
from wasmParser import sectionStructure as ss
# reload(ss)
from wasmParser.parser import insert_after_key

from strategies.state import get_dist
from strategies.state import getDist

import os
import json
import pickle

def import_insertion(parsedSection, alpha, beta, ratio):
    current_dir = os.path.dirname(__file__)
    json_path = os.path.join(current_dir, "data", "import_func_names.json")

    with open(json_path, "r", encoding="utf-8") as f:
        all_names = set(json.load(f))

    import_keys = list(parsedSection["Import"].keys())
    if len(import_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(import_keys))
        if iter != len(import_keys):
            iter += 1

    existing_imports = set()
    # print(f"parsedSection['Import']: {parsedSection.get('Import')}")
    # print(f"type: {type(parsedSection.get('Import'))}")
    for entry in parsedSection['Import'].values():
        if entry.type == "func":
            existing_imports.add(entry.name)
    candidates = list(all_names - existing_imports)
    
    for _ in range(iter):

        if candidates:
            beta_idx = getDist(alpha,beta,len(candidates))
            beta_idx = max(0, min(beta_idx, len(candidates) - 1))
            new_import_name = candidates[beta_idx]
            # print(idx)
            # print(f"Selected new import: {new_import_name}")
        else:
            raise ValueError("[Cannot apply] All import function name candidates already exist in the binary!")
        
        beta_idx = getDist(alpha,beta,len(import_keys))
        beta_idx = max(0, min(beta_idx, len(import_keys) - 1))
        selected_import_key = import_keys[beta_idx]
        # print(selected_import)

        type_keys = list(parsedSection['Type'].keys())
        beta_idx = getDist(alpha,beta,len(type_keys))
        beta_idx = max(0, min(beta_idx, len(type_keys) - 1))
        selected_import_type = type_keys[beta_idx]
        new_import_key = '$wade.'+new_import_name
        new_import_code = f'  (import "env" "{new_import_name}" (func {new_import_key} (type {selected_import_type})))\n'
        new_import = ss.IMPORT(type='func', name=new_import_name, line=[new_import_code, 'A'])
        # print(new_import_code)
        insert_after_key(parsedSection['Import'], selected_import_key, new_import_key, new_import)

def function_insertion(parsedSection, alpha, beta, ratio):
    current_dir = os.path.dirname(__file__)
    function_path = os.path.join(current_dir, "data", "function_body.pkl")
    
    with open(function_path, 'rb') as f:
        saved_functions = pickle.load(f)

    signatures = list()
    signature_type = dict()
    for type_key in parsedSection['Type']:
        params = parsedSection['Type'][type_key].param or []
        results = parsedSection['Type'][type_key].result or []
        signature = "param" + "".join(params) + "result" + "".join(results)
        
        if signature in saved_functions:
            signatures.append(signature)
            signature_type[signature] = type_key
    
    if len(signatures) == 0:
        print('No identical function type\n')
        return

    function_keys = list(parsedSection["Function"].keys())
    if len(function_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(function_keys))
        if iter != len(function_keys):
            iter += 1

    idx = 0
    for _ in range(iter):
        beta_idx = getDist(alpha,beta,len(signatures))
        beta_idx = max(0, min(beta_idx, len(signatures) - 1))
        selected_signature = signatures[beta_idx]

        beta_idx = getDist(alpha,beta,len(saved_functions[selected_signature]))
        beta_idx = max(0, min(beta_idx, len(selected_signature) - 1))
        new_func_code = saved_functions[selected_signature][beta_idx]
        
        idx += 1
        new_func_code = new_func_code.format(new_func_name=f'$wadefunc{idx}', 
        
        new_func_type=signature_type[selected_signature])
        new_func = ss.FUNCTION(header='', body=[[new_func_code,'FunctionInsertion']])

        beta_idx = getDist(alpha,beta,len(function_keys))
        beta_idx = max(0, min(beta_idx, len(function_keys) - 1))
        selected_function_key = function_keys[beta_idx]
        insert_after_key(parsedSection['Function'], selected_function_key, f'$wadefunc{idx}', new_func)

        # print(selected_function_key)
        # print(new_func_code)
        # return
def function_body_cloning(parsedSection, alpha, beta, ratio):

    RE_CALL = re.compile(r'^\s*call\s+(?P<id>\$\S+)')
    RE_FUNC_ID = re.compile(r'^\s*\(func\s+(?P<id>\$\w+)')

    functions = parsedSection['Function']
    func_keys = list(functions)

    funcID_proxyID = dict()
    func_idx = 0
    iter = round(len(functions)*ratio)
    for _ in range(iter):
        while (True):
            beta_idx = getDist(alpha,beta,len(func_keys))
            beta_idx = max(0, min(beta_idx, len(func_keys) - 1))
            selected_function = func_keys[beta_idx]

            if selected_function not in funcID_proxyID:
                func_idx += 1
                funcID_proxyID[selected_function] = f'$wadefunc{func_idx}'
                break

    proxy_target = {k: 0 for k in funcID_proxyID.keys()}
    # print(funcID_proxyID)
    # print(proxy_target)

    for f in functions:

        function = parsedSection['Function'][f]

        if function.body == None:
            continue
        
        new_body = list()
        body = function.body

        for offset, code in enumerate(body):
            code_line = code[0]
            call_match = RE_CALL.match(code_line)
            if call_match:
                func_id = call_match.group('id')
                if (func_id in funcID_proxyID) and (proxy_target[func_id] == 0):
                    proxy_target[func_id] = 1
                    new_body_code = code_line.replace(func_id,funcID_proxyID[func_id])
                    # print(new_body_code)
                    new_body.append([new_body_code, "FUNCTIONCLONING"])
                else:
                    proxy_target[func_id] = 0
                    new_body.append([code_line, ""])
            else:
                new_body.append([code_line, ""])
        functions[f].body = new_body

    for funcID in funcID_proxyID:
        selected_function = parsedSection['Function'][funcID]

        beta_idx = getDist(alpha,beta,len(func_keys))
        beta_idx = max(0, min(beta_idx, len(func_keys) - 1))
        selected_location = func_keys[beta_idx]

        new_header_id = funcID_proxyID[funcID]
        old_header = selected_function.header
        old_header_id = RE_FUNC_ID.match(old_header[0][0]).group('id')
        new_header = old_header[0][0].replace(old_header_id, new_header_id, 1)
        if len(old_header) > 1:
            for i in range(1,len(old_header)):
                new_header += old_header[i][0]

        new_func = ss.FUNCTION(header=[[new_header,"FUNCTIONCLONING"]], body=selected_function.body)
        insert_after_key(parsedSection['Function'], selected_location, new_header_id, new_func)

    
def export_insertion(parsedSection, alpha, beta, ratio):
    current_dir = os.path.dirname(__file__)
    json_path = os.path.join(current_dir, "data", "export_func_names.json")

    with open(json_path, "r", encoding="utf-8") as f:
        all_names = set(json.load(f))

    export_keys = list(parsedSection["Export"].keys())
    func_keys = list(parsedSection["Function"].keys())

    if len(export_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(export_keys))
        if iter != len(export_keys):
            iter += 1

    for _ in range(iter):
        candidates = list(all_names - set(export_keys))

        if candidates:
            beta_idx = getDist(alpha,beta,len(candidates))
            beta_idx = max(0, min(beta_idx, len(candidates) - 1))
            new_export_name = candidates[beta_idx]
            # print(idx)
            # print(f"Selected new import: {new_import_name}")
        else:
            raise ValueError("[Cannot apply] All export function name candidates already exist in the binary!")
        
        beta_idx = getDist(alpha,beta,len(export_keys))
        beta_idx = max(0, min(beta_idx, len(export_keys) - 1))
        selected_export_key = export_keys[beta_idx]
        beta_idx = getDist(alpha,beta,len(func_keys))
        beta_idx = max(0, min(beta_idx, len(func_keys) - 1))
        new_export_func =  func_keys[beta_idx]
        new_export_code = f'  (export "{new_export_name}" (func {new_export_func}))\n'
        new_export = ss.EXPORT(funcID=new_export_func, line=[new_export_code, 'ExportInsertion'])
        # print(new_import_code)
        insert_after_key(parsedSection['Export'], selected_export_key, new_export_name, new_export)

def data_insertion(parsedSection, alpha, beta, ratio):
    memory_map = {}
    data_lengths = list()

    data_keys = list(parsedSection['Data'].keys())
    
    # if len(data_keys) == 0:
    #     memory_keys = list(parsedSection['Data'].keys())
    #     if len(memory_keys) > 0:
    #         new_memory = ss.MEMORY(offset=new_data_offset, length=new_data_length, data=new_data_bytes, line=[new_data_code, 'DataInsertion'])
    #         insert_after_key(parsedSection['Data'], selected_data_key, new_data_name, new_data)


    for entry in parsedSection["Data"].values():
        offset = entry.offset
        data_value = entry.data
        data_lengths.append(entry.length)
        
        for i, b in enumerate(data_value):
            memory_map[offset + i] = b
    
    memory_map = dict(sorted(memory_map.items()))

    min_offset = min(memory_map.keys())
    max_offset = max(memory_map.keys())

    data_offsets = list()

    if len(data_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(data_keys))
        if iter != len(data_keys):
            iter += 1

    new_data_index = 0
    # frb = open(file_path, 'rb')
    
    for _ in range(iter):
        new_data_index += 1
        
        beta_idx = getDist(alpha,beta,len(data_lengths))
        beta_idx = max(0, min(beta_idx, len(data_lengths) - 1))
        new_data_length = data_lengths[beta_idx]

        data_offsets = []
        for start_offset in range(min_offset, max_offset + 1):
            if start_offset + new_data_length <= max_offset + 1:
                data_offsets.append(start_offset)

        beta_idx = getDist(alpha,beta,len(data_keys))
        beta_idx = max(0, min(beta_idx, len(data_keys) - 1))
        selected_data_key = data_keys[beta_idx]

        beta_idx = getDist(alpha,beta,len(data_offsets))
        beta_idx = max(0, min(beta_idx, len(data_offsets) - 1))
        new_data_offset = data_offsets[beta_idx]
        new_data_bytes = bytes([memory_map.get(new_data_offset + i, 0) for i in range(new_data_length)])
        new_data_string = ''.join(f'\\{b:02x}' for b in new_data_bytes)
        # print(new_data_string)
        new_data_name = f'$wadeData{new_data_index}'
        new_data_code = f'  (data {new_data_name} (i32.const {new_data_offset}) "{new_data_string}")\n'
        new_data = ss.DATA(offset=new_data_offset, length=new_data_length, data=new_data_bytes, line=[new_data_code, 'DataInsertion'])

        insert_after_key(parsedSection['Data'], selected_data_key, new_data_name, new_data)

def escape_bytes_for_wat(data_bytes: bytes) -> str:
    escaped = []
    for b in data_bytes:
        # Printable ASCII & safe characters
        if 0x20 <= b <= 0x7E and b not in (0x22, 0x5C):  # Exclude '"' (34) and '\' (92)
            escaped.append(chr(b))
        else:
            escaped.append(f'\\{b:02x}')
    return ''.join(escaped)

def data_encryption(parsedSection, alpha, beta, ratio):
    current_dir = os.path.dirname(__file__)
    json_path = os.path.join(current_dir, "data", "data_decryption_func")

    with open(json_path, "r", encoding="utf-8") as f:
        func_decrypt = f.readlines()
    code_lines = list()
    for code_line in func_decrypt:
        code_lines.append([code_line,'DataEncryption'])
    
    new_type_param = ['i32', 'i32']
    new_type_id = None
    type_keys = list(parsedSection['Type'].keys())
    for key in type_keys:
        if parsedSection['Type'][key].param == new_type_param:
            new_type_id = key
            # print('[log] Use already defined type:', new_type_id)
            break
    if new_type_id is None:
        last_type = type_keys[-1]
        new_type_id = '$wadeDecryptType'
        new_type_code = f'  (type $wadeDecryptType (func (param i32 i32)))'
        new_type = ss.TYPE(param=new_type_param, result=None, line=new_type_code)
        insert_after_key(parsedSection['Type'], last_type, new_type_id, new_type)
        print('[log] Use newly defined type:', new_type_id)

    last_func = list(parsedSection['Function'].keys())[-1]
    decrypt_func = ss.FUNCTION(type=new_type_id, param=new_type_param, result=None, local=None, header='', body=code_lines)
    insert_after_key(parsedSection['Function'], last_func, '$wade_decrypt', decrypt_func)

    xor_key = b'wadedataencryption'
    data_keys = list(parsedSection['Data'].keys())
    candidate_data = set(data_keys)
    
    iter = int(ratio*len(data_keys))
    if iter != len(data_keys):
        iter += 1

    init_func_body = list()
    init_func_body.append(['\n  (func $wadeInit\n','DataEncryption'])
    
    for _ in range(iter):
        
        # print(candidate_data)
        beta_idx = getDist(alpha,beta,len(candidate_data))
        beta_idx = max(0, min(beta_idx, len(candidate_data) - 1))
        selected_data = list(candidate_data)[beta_idx]
        # print(selected_data)
        candidate_data.remove(selected_data)

        data_raw = parsedSection['Data'][selected_data].data
        data_encrypted = bytes([
            b ^ xor_key[i % len(xor_key)]
            for i, b in enumerate(data_raw)
        ])
        data_escaped = escape_bytes_for_wat(data_encrypted)
        # parsedSection['Data'][selected_data].data = data_encrypted
        data_offset = parsedSection['Data'][selected_data].offset
        data_length = parsedSection['Data'][selected_data].length

        parsedSection['Data'][selected_data].line = [f'  (data {selected_data} (i32.const {data_offset}) "{data_escaped}")\n','DataEncrypted']

        init_func_body.append([f'    (call $wade_decrypt (i32.const {data_offset}) (i32.const {data_length}))\n','DataEncryption'])
    
    init_func_body.append(['  )\n','DataEncryption'])
    init_func = ss.FUNCTION(type=None, param=None, result=None, local=None, header='', body=init_func_body)
    insert_after_key(parsedSection['Function'], '$wade_decrypt', '$wadeInit', init_func)
    

    new_start = ss.START(line=['  (start $wadeInit)\n','DataEncryption'])
    if len(parsedSection['Start']) == 0:
        parsedSection['Start'] = {'start':new_start}


def global_insertion(parsedSection, alpha, beta, ratio):
    
    global_keys = list(parsedSection['Global'].keys())

    if len(global_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(global_keys))
        if iter != len(global_keys):
            iter += 1

    new_global_index = 0
    # frb = open(file_path, 'rb')
    
    for _ in range(iter):
        new_global_index += 1

        is_mut = random.choice([True, False])
        global_type = random.choice(['i32', 'i64', 'f32', 'f64'])
        new_globalID = f'$wadeGlobal{new_global_index}'

        if global_type.startswith('i'):
            global_value = random.randint(0, 2**32 - 1)
            global_init = f"({global_type}.const {global_value})"
        else:
            global_value = random.uniform(-1e3, 1e3)
            global_init = f"({global_type}.const {global_value:.6f})"

        if is_mut:
            global_code = f"  (global $wadeGlobal{new_global_index} (mut {global_type}) {global_init})\n"
        else:
            global_code = f"  (global $wadeGlobal{new_global_index} {global_type} {global_init})\n"

        beta_idx = getDist(alpha,beta,len(global_keys))
        beta_idx = max(0, min(beta_idx, len(global_keys) - 1))
        selected_global = global_keys[beta_idx]
        new_global = ss.GLOBAL(type={global_type}, value=int(global_value), line=[global_code,"GlobalInsertion"])
        insert_after_key(parsedSection['Global'], selected_global, new_globalID, new_global)
    
def function_sig_insertion(parsedSection, alpha, beta, ratio):
    
    wasm_types = ['i32', 'i64', 'f32', 'f64']
    type_keys = list(parsedSection['Type'].keys())

    params_results = list()
    for key in type_keys:
        params = parsedSection['Type'][key].param
        if params == None:
            # print('none')
            params = []
        results = parsedSection['Type'][key].result
        if results == None:
            # print('none')
            results = []
        params_results.append([params,results])

    
    if len(type_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(type_keys))
        if iter != len(type_keys):
            iter += 1

    new_type_index = 0
    # frb = open(file_path, 'rb')
    
    for _ in range(iter):
        new_type_index += 1
    
        while True:
            num_params = getDist(alpha, beta, 10)
            num_results = getDist(alpha, beta, 10)

            params = [random.choice(wasm_types) for _ in range(num_params)]
            results = [random.choice(wasm_types) for _ in range(num_results)]
            
            if [params,results] not in params_results:
                break
        
        # print(params,results)
        # break
        if len(params) == 0:
            params = None
            params_str = ''
        else:
            params_str = ' (param '+' '.join(params)+')'
        if len(results) == 0:
            results = None
            results_str = ''
        else:
            results_str = ' (result '+' '.join(results)+')'
            
        # print(params_str,results_str)
        beta_idx = getDist(alpha,beta,len(type_keys))
        beta_idx = max(0, min(beta_idx, len(type_keys) - 1))
        selected_type = type_keys[beta_idx]
        
        new_type_id = f'$wade{new_type_index}'
        new_type_code = [f'  (type {new_type_id} (func{params_str}{results_str}))\n','TypeInsertion']
        new_type = ss.TYPE(param=params, result=results, line=new_type_code)
        insert_after_key(parsedSection['Type'], selected_type, new_type_id, new_type)
        
    
def element_insertion(parsedSection, alpha, beta, ratio):
    
    func_keys = list(parsedSection['Function'].keys())
    elem_keys = list(parsedSection['Element'].keys())

    if len(elem_keys) <100:
        iter = int(ratio*100)
    else:
        iter = int(ratio*len(elem_keys))
        if iter != len(elem_keys):
            iter += 1

    elem_idx = 0
    for _ in range(iter):

        beta_idx = getDist(alpha, beta, len(func_keys))
        beta_idx = max(0, min(beta_idx, len(func_keys) - 1))
        selected_func = func_keys[beta_idx]

        new_elem_code = f'  (elem (table $wadetable) (i32.const {elem_idx}) {selected_func})\n'
        new_elem = ss.ELEMENT(line=[new_elem_code,'ElementInsertion'])
        
        if len(elem_keys) == 0:
            parsedSection['Element'][str(elem_idx)] = new_elem
        else:
            beta_idx = getDist(alpha, beta, len(elem_keys))
            beta_idx = max(0, min(beta_idx, len(elem_keys) - 1))
            selected_elem = elem_keys[beta_idx]
            insert_after_key(parsedSection['Element'], selected_elem, str(elem_idx), new_elem)
        elem_idx += 1

    table_keys = list(parsedSection['Table'].keys())
    
    new_table_code = f'  (table $wadetable {elem_idx} funcref)\n'
    new_table = ss.TABLE(line=[new_table_code,'ElementInsertion'])
        
    if len(table_keys) == 0:
        parsedSection['Table']['$wadeTable'] = new_table
    else:
        last_table = table_keys[-1]
        insert_after_key(parsedSection['Table'], last_table, '$wadetable', new_table)