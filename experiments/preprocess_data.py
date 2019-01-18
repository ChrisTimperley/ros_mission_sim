import os
import json
import csv

import argparse

def setup_arg_parser():
    parser = argparse.ArgumentParser(description='Preprocess traces')
    parser.add_argument('traces', type=str, action='store',
                       help='path to trace files.')
    parser.add_argument('--ignore-cat', action='store_true',
                        default=False,
                        help='ignore categorical fields of the data.')
    parser.add_argument('--separate-params', action='store_true',
                        default=False,
                        help='put parameters in a separate file')
    parser.add_argument('--output-dir', action='store', type=str,
                        default='out/',
                        help='the directory where the results will be stored')
    args = parser.parse_args()
    return args


def transform_data(data_dir, output_dir, ignore_cat, separate_params):
    for name in os.listdir(data_dir):
        if not name.endswith('json'):
            continue
        m_hash = name[:-len('.json')]
        filename = os.path.join(data_dir, name)
        with open(filename, 'r') as f:
            j = json.load(f)
            index = 0
            for c in j['traces'][0]['commands']:  # TODO handle the case with multiple traces
                new_filename_temp = "{}_{}_{}.csv".format(c['command']['type'], m_hash, index)
                new_filename = os.path.join(output_dir, new_filename_temp)
                states = c['states']
                if not ignore_cat:
                    keys = list(states[0].keys())

                else:
                    keys = [n for n in sorted(states[0]) if type(states[0][n]) not in [bool, str]]
                if not separate_params:
                    if not ignore_cat:
                        p = {'p_{}'.format(k): v for k, v in c['command']['parameters'].items()}
                    else:
                        p = {'p_{}'.format(k): v for k, v in c['command']['parameters'].items() if type(v) not in [bool, str]}
                    keys.extend(sorted(p.keys()))
                    for s in states:
                        s.update(p)
                if not ignore_cat:
                    for s in states:
                        if "mode" in s:
                            s["mode"] = 0 if s["mode"] == "AUTO" else 1 # TODO fix this. There are other modes that AUTO and GUIDED
                        for k,v in s.items():
                            if type(v) == bool:
                                s[k] = int(v)
                with open(new_filename, 'w') as output_file:
                    dict_writer = csv.DictWriter(output_file, keys, extrasaction='ignore')
                    dict_writer.writeheader()
                    dict_writer.writerows(c['states'])
                if separate_params:
                    param_filename = os.path.join(output_dir, c['command']['type'] + ".csv")
                    param_keys = list(c['command']['parameters'].keys())
                    param_keys.append('filename')
                    print_header = False
                    if not os.path.exists(param_filename):
                        print_header = True
                    with open(param_filename, 'a') as output_file:
                        dict_writer = csv.DictWriter(output_file, param_keys)
                        if print_header:
                            dict_writer.writeheader()
                        p = c['command']['parameters']
                        p['filename'] = new_filename_temp
                        dict_writer.writerow(p)
                index += 1

if __name__=="__main__":
    args = setup_arg_parser()
    transform_data(args.traces, args.output_dir, args.ignore_cat, args.separate_params)
