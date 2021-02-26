# Copyright (c) Microsoft Corporation.
# Licensed under the MIT license.

import os, subprocess
import re

local_dll_path = '%s/antares_hlsl_v0.2dev0_x64.dll' % os.environ['ANTARES_DRIVER_PATH']
if not os.path.exists(local_dll_path):
    os.system(f'curl -Ls https://github.com/microsoft/antares/releases/download/v0.1.0/antares_hlsl_v0.2dev0_x64.dll -o {local_dll_path}')

def get_execution_parallism():
    return 1

def do_native_translation_v2(codeset, **kwargs):
    kernel_name, in_args, out_args, body = codeset

    registers = []
    for i, buf in enumerate(in_args):
      registers.append('StructuredBuffer<%s> %s: register(t%d);\n' % (buf[0], buf[1], i))
    for i, buf in enumerate(out_args):
      registers.append('RWStructuredBuffer<%s> %s: register(u%d);\n' % (buf[0], buf[1], i))

    def get_extent(key, defval=1):
      str_pat = f'// [thread_extent] {key} = '
      idx = body.find(str_pat)
      if idx >= 0:
        return int(body[idx+len(str_pat):body.index('\n', idx)])
      return defval

    lines, lds = [], []
    for line in body.split('\n'):
      # Parse Group Shared
      pos = line.find(' __shared__ ')
      if pos >= 0 and ' ' * pos == line[:pos]:
        lds.append('groupshared ' + line[pos + len(' __shared__ '):])
      else:
        # Convert L1 booling math operator
        def wrap_bool_math_operator(line):
          comma_lv = [0] * len(line)
          last_lv = 0
          for i in range(len(line)):
            if line[i] == '(':
              comma_lv[i] = last_lv + 1
            elif line[i] == ')':
              comma_lv[i] = last_lv - 1
            elif line[i] in (':', '?') and last_lv != 1:
              return line
            else:
              comma_lv[i] = last_lv
            last_lv = comma_lv[i]

          if line[-2:] != ');':
            return line
          before = line.index(' = (')
          pos = line.index(' ? ', before)
          after = line.index(' : ', pos)
          output = line[0:before].lstrip()
          cond = line[before+len(' = ('):pos]
          in_true = line[pos+len(' ? '):after]
          in_false = line[after+len(' : '):-2]
          indent = ' ' * (before - len(output))
          normal_line = indent + 'if (%s) { %s = %s; } else { %s = %s; }' % (cond, output, in_true, output, in_false)
          return normal_line

        pos = line.find(' ? ')
        if pos >= 0 and line.find(' ? ', pos + 1) < 0:
          line = wrap_bool_math_operator(line)
          lines.append(line)
        else:
          lines.append(line)

    body = '\n'.join(lines)
    body = re.sub(r'\b__syncthreads\b', 'GroupMemoryBarrierWithGroupSync', body);
    lds = '\n'.join(lds)
    registers = ''.join(registers)

    full_body = f'''{lds}
{registers}{kwargs['attrs'].blend}
[numthreads({get_extent('threadIdx.x')}, {get_extent('threadIdx.y')}, {get_extent('threadIdx.z')})]
void CSMain(uint3 threadIdx: SV_GroupThreadID, uint3 blockIdx: SV_GroupID, uint3 dispatchIdx: SV_DispatchThreadID) {{
  {body}
}}
'''
    return full_body