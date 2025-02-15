import fiona
import shapely
from shapely.geometry import Polygon, shape
import rtree
import pprint
import timeit
import csv
import os
import re
import xlrd
import json

"""Applies the 2014 electoral maps and results to the 2018 electoral map.

Methodology:
First, we determine which 2018 ridings each 2014 polling location intersects. If a polling location completely intersects
a riding, all its votes are assigned to the riding. If a location intersects more than one riding, its votes are divide based
on the proportion of the location that lies in each riding.

Advanced polling votes are divided with the same strategy, but based on riding instead of polling location because advanced 
poll votes are only available on a riding scale.
"""

"""Taken from:
https://www.elections.on.ca/content/dam/NGW/sitecontent/2014/historical-results/2014/Summary%20of%20Valid%20Ballots%20Cast%20-%202014%20General%20Election.pdf
"""
POP_VOTE_2014 = { 'LIB' : 38.7, 'PC' : 31.3, 'NDP' : 23.7, 'OTH' : 6.1}
POP_VOTE_2011 = { 'LIB' : 37.65, 'PC' : 35.45, 'NDP' : 22.74, 'OTH' : 4.1}

class Poll:
    
    def __init__(self):
        self.riding_id = 0
        self.poll_id = 0

class Riding:

    def __init__(self):
        self.id = 0
        self.name = ''
        self.shape = Polygon()
        self.polls = list()
        self.ridings = list()
        self.results = dict()
        self.percents = dict()
        self.swings = dict()

    def json_encode(self):
        return {'name' : self.name.replace('\u0097', '-'), 'id' : self.id, 'results' : self.results, 
                'percents' : self.percents, 'swings' : self.swings}

"""Gets the ridings that intersect a given polling location's shape.
Returns a list of tuples containing the id of the riding, and the total area of their intersection.
"""
def get_intersecting_ridings(poll_shape, ridings_dict, ridings_index):
    intersections = list()
    possible = ridings_index.intersection(poll_shape.bounds)
    for id in possible:
        riding = ridings_dict[id]
        if poll_shape.intersects(riding.shape):
            intersect = poll_shape.intersection(riding.shape)
            intersections.append((id, intersect.area))
    return intersections

"""Assigns weights of past polling locations to 2018 ridings.
"""
def assign_poll_weights(year, ridings_2018, ridings_index):
    with fiona.open(f'data/{year}/polls/polls.shp') as polls_file_2014:
        for poll_record in polls_file_2014:
            poll = Poll()
            poll.riding_id = poll_record['properties']['ED_ID']
            poll.poll_id = poll_record['properties']['POLL_DIV_1']
            poll_shape = shape(poll_record['geometry'])
            intersecting = get_intersecting_ridings(poll_shape, ridings_2018, ridings_index)
            sum_area = 0
            for intersect in intersecting:
                sum_area += intersect[1]
            for intersect in intersecting:
                riding = ridings_2018[intersect[0]]
                weight = intersect[1] / sum_area
                riding.polls.append((poll, weight))

"""Assign weights of past ridings to the 2018 ridings based on the area of overlap.  This is inaccurate and is used 
only for advanced polls, which have no geographic location and cannot be assigned more precisely.
"""
def assign_riding_weights(year, ridings_2018, ridings_index):
    with fiona.open(f'data/{year}/districts/districts.shp') as ridings_file_2014:
        for riding_record in ridings_file_2014:
            riding_shape = shape(riding_record['geometry'])
            intersecting = get_intersecting_ridings(riding_shape, ridings_2018, ridings_index)
            sum_area = 0
            for intersect in intersecting:
                sum_area += intersect[1]
            for intersect in intersecting:
                riding = ridings_2018[intersect[0]]
                weight = intersect[1] / sum_area
                riding.ridings.append((riding_record['properties']['ED_ID'], intersect[1] / sum_area))

"""Loads riding data from a given year from the shapefiles.
"""
def load_riding_data(year):
    with fiona.open('data/' + str(year) + '/districts/districts.shp') as ridings_file_2018:
        ridings_2018 = dict()
        riding_index = rtree.index.Index()
        for riding_record in ridings_file_2018:
            riding = Riding()
            riding.name = riding_record['properties']['ENGLISH_NA']
            riding.id = riding_record['properties']['ED_ID']
            riding.shape = shape(riding_record['geometry'])
            ridings_2018[riding.id] = riding
            riding_index.add(riding.id, riding.shape.bounds)
        return ridings_2018, riding_index

"""Loads the list of candidates from the candidates file. Returns a dict of candidates by riding number.
"""
def load_candidate_list(year):
    with open(f'data/{year}/results/candidates_fixed.csv', encoding='utf-8') as candidate_file:
        candidates = dict()
        reader = csv.reader(candidate_file)
        for line in reader:
            riding_candidates = dict()
            riding_candidates[line[1].upper()] = 'LIB'
            riding_candidates[line[2].upper()] = 'PC'
            riding_candidates[line[3].upper()] = 'NDP'
            #remove byte order mark from any name that has it
            candidates[line[0].upper().replace('\ufeff', '')] = riding_candidates
        return candidates

"""Determines the party assignment of results in a column based on the file header and the list of candidates by riding
and party.
"""
def assign_party_cols(candidates_dict, results_sheet, start_col, header_row, stop_marker):
    #assign result columns to party
    party_cols = dict()
    #names start at the third column
    col = start_col
    while results_sheet.cell_value(header_row, col) != stop_marker:
        candidate_name = results_sheet.cell_value(1, col)
        if candidate_name in candidates_dict:
            party_cols[col] = candidates_dict[candidate_name]
        else:
            party_cols[col] = 'OTH'
        col += 1
    return party_cols

"""Gets the poll number from a poll name. Returns ADV if the poll is an advanced poll, or None if there was no number found
"""
def get_poll_number(name):
    if name.startswith('ADV'):
        return 'ADV'
    digit_matches = re.findall(r'^\d+', name)
    if len(digit_matches) > 0:
        return int(digit_matches[0])
    else:
        return None

"""Assigns poll results from one row. Usually returns None, but if the row being processed combines its results with another
poll, it will return the name of that poll instead.
"""
def assign_row_results(row, results_sheet, party_cols, riding_results, name_col):
    poll_name = results_sheet.cell_value(row, name_col)
    #convert the name to an int if we can, because sometimes they appears as floats which won't work
    try:
        poll_name = int(poll_name)
    except ValueError:
        pass
    poll_number = get_poll_number(str(poll_name))
    if poll_number is None:
        return
    poll_info_text = str(results_sheet.cell_value(row, 2))
    #also check the first column because it shows up there sometimes too
    if poll_info_text is '':
        poll_info_text = results_sheet.cell_value(row, 1)
    if poll_info_text is not '':
        if 'COMBINED WITH POLL' in poll_info_text:
            return int(re.findall(r'\d+', poll_info_text)[0])
        if 'NO POLL' in poll_info_text:
            return
    row_results = dict()
    for col, party in party_cols.items():
        if row_results.get(party) is None:
            row_results[party] = 0
        value = results_sheet.cell_value(row, col)
        if 'COMBINED WITH POLL' in str(value):
            return int(re.findall(r'\d+', value)[0])
        if 'NO POLL' in str(value):
            return
        row_results[party] += int(value)
    if riding_results.get(poll_number) is None:
        riding_results[poll_number] = row_results
    else:
        for key in row_results.keys():
            riding_results[poll_number][key] += row_results[key]

"""Loads poll-by-poll results and returns a dict. The dict is keyed by riding id, and the values are also dicts containing
results by poll number, keyed by party descriptor. Some polls are combined with other polling locations. The votes are split
across all combined polls evenly after the fact. Other polls have taken no votes, they are not recorded. Advanced polls do
not appear in the poll shapefiles and are listed under one heading, 'ADV'.
"""

"""The poll by poll results are drastically different between years. We need special logic for each year so they get separate functions."""
def load_poll_results_2014(ridings, candidates):
    results = dict()
    for result_file_name in os.listdir('data/2014/results/poll_results/'):
        results_sheet = xlrd.open_workbook('data/2014/results/poll_results/' + result_file_name).sheet_by_index(0)
        riding_num = int(re.findall(r'\d+', result_file_name)[0])
        results[riding_num] = dict()
        party_cols = assign_party_cols(candidates[ridings[riding_num].name], results_sheet, 3, 1, '')
        #WARNING: shady excel parsing past this point
        #poll results start at two
        row = 2
        combined = dict()
        #the poll results end with a totals row
        while results_sheet.cell_value(row, 0) != 'Totals':
            comb_poll = assign_row_results(row, results_sheet, party_cols, results[riding_num], 0)
            if comb_poll is not None:
                if combined.get(comb_poll) is None:
                    combined[comb_poll] = list()
                combined[comb_poll].append(int(re.findall(r'\d+', results_sheet.cell_value(row, 0))[0]))
            row += 1
        #split combined polls back into their original assignments
        for poll, combined in combined.items():
            split_poll_results = results[riding_num][poll]
            for party, result in split_poll_results.items():
                split_poll_results[party] = result / (len(combined) + 1)
            results[riding_num][poll] = split_poll_results
            for combined_poll in combined:
                results[riding_num][combined_poll] = split_poll_results
    return results

"""The poll by poll results are drastically different between years. We need special logic for each year so they get separate functions."""
def load_poll_results_2011(ridings, candidates):
    results = dict()
    for result_file_name in os.listdir('data/2011/results/poll_results/'):
        results_sheet = xlrd.open_workbook('data/2011/results/poll_results/' + result_file_name).sheet_by_index(0)
        #the file also has "2011" in it so we take the second group of numbers found
        riding_num = int(re.findall(r'\d+', result_file_name)[1])
        results[riding_num] = dict()
        party_cols = assign_party_cols(candidates[ridings[riding_num].name], results_sheet, 5, 1, 'REJECTED')
        if 'LIB' not in party_cols.values() or 'PC' not in party_cols.values() or 'NDP' not in party_cols.values():
            print(f'WARNING: no candidate for {ridings[riding_num].name}')
        #WARNING: shady excel parsing past this point
        #poll results start at two
        row = 2
        combined = dict()
        #the poll results end with a totals row
        while results_sheet.cell_value(row, 0) != 'TOTALS:':
            comb_poll = assign_row_results(row, results_sheet, party_cols, results[riding_num], 2)
            if comb_poll is not None:
                if combined.get(comb_poll) is None:
                    combined[comb_poll] = list()
                #first try and direct convert to an int
                try:
                    combined[comb_poll].append(int(results_sheet.cell_value(row, 2)))
                #if that fails use a regex to extract
                except ValueError:
                    combined[comb_poll].append(int(re.findall(r'\d+', results_sheet.cell_value(row, 2))[0]))
            row += 1
        #split combined polls back into their original assignments
        for poll, combined in combined.items():
            split_poll_results = results[riding_num][poll]
            for party, result in split_poll_results.items():
                split_poll_results[party] = result / (len(combined) + 1)
            results[riding_num][poll] = split_poll_results
            for combined_poll in combined:
                results[riding_num][combined_poll] = split_poll_results
    return results

def calculate_results(ridings_2018, results, pop_vote):
    for riding in ridings_2018.values():
        riding.results['LIB'] = 0
        riding.results['PC'] = 0
        riding.results['NDP'] = 0
        riding.results['OTH'] = 0
        for poll, weight in riding.polls:
            try:
                poll_results = results[poll.riding_id][poll.poll_id]
            except KeyError:
                #this poll was probably not taken, don't worry about it
                pass
            for party, result in poll_results.items():
                riding.results[party] += result * weight
        for riding_id, weight in riding.ridings:
            advanced_results  = results[riding_id]['ADV']
            for party, result in advanced_results.items():
                riding.results[party] += result * weight
        vote_sum = 0
        for _, result in riding.results.items():
            vote_sum += result
        for party, result in riding.results.items():
            riding.percents[party] = (riding.results[party] / vote_sum) * 100
            riding.swings[party] = riding.percents[party] - pop_vote[party]

"""Projects 2018 using results from a previous election"""
def project(year):
    ridings_2018, riding_index = load_riding_data(2018)
    ridings, _ = load_riding_data(year)
    print('Riding data loaded.')
    candidates = load_candidate_list(year)
    print('Candidate list loaded.')
    if year == '2014':
        results = load_poll_results_2014(ridings, candidates)
    elif year == '2011':
        results = load_poll_results_2011(ridings, candidates)
    print('Past results loaded.')
    assign_poll_weights(year, ridings_2018, riding_index)
    print('Poll weights assigned.')
    assign_riding_weights(year, ridings_2018, riding_index)
    print('Riding weights assigned.')
    if year == '2014':
        calculate_results(ridings_2018, results, POP_VOTE_2014)
    elif year == '2011':
        calculate_results(ridings_2018, results, POP_VOTE_2011)
    print('Results calculated.')
    return ridings_2018

start = timeit.time.time()
print('Projecting 2011.')
projected_2011 = project('2011')
print('Projecting 2014.')
projected_2014 = project('2014')
ridings_2018 = list()
#average the two election projections, 2011 gets 25 percent and 2014 gets 75 percent
for riding_id in projected_2011.keys():
    riding_2011 = projected_2011[riding_id]
    riding_2014 = projected_2014[riding_id]
    riding_2018 = Riding()
    riding_2018.name = riding_2011.name
    riding_2018.id = riding_2011.id
    for party in riding_2011.percents.keys():
        riding_2018.percents[party] = (0.25 * riding_2011.percents[party]) + (0.75 * riding_2014.percents[party])
    for party in riding_2011.swings.keys():
        riding_2018.swings[party] = (0.25 * riding_2011.swings[party]) + (0.75 * riding_2014.swings[party])
    for party in riding_2011.results.keys():
        riding_2018.results[party] = (0.25 * riding_2011.results[party]) + (0.75 * riding_2014.results[party])
    ridings_2018.append(riding_2018)
print('Outputting data to ridings_2018.json')
json.dump(ridings_2018, open('ridings_2018.json', 'w'), 
          default=lambda riding: riding.json_encode(), indent=4)
end = timeit.time.time()
print('Took ' + str(end - start) + ' seconds.')
  