"""
kadi.cmds.states

This module provides the functions for dynamically determining Chandra commanded states
based entirely on known history of commands.
"""
from __future__ import division, print_function, absolute_import

import collections
import itertools
import warnings

import numpy as np
import six
from six.moves import range

from astropy.table import Table, Column

from . import cmds as commands

from Chandra.cmd_states import decode_power
from Chandra.Time import DateTime
import Chandra.Maneuver
from Quaternion import Quat
import Ska.Sun

# Dict that allows determining command params (e.g. obsid 'ID' or SIM focus 'POS')
# for a particular command.
REV_PARS_DICT = commands.rev_pars_dict

# Registry of Transition classes with state transition name as key.  A state transition
# may be generated by several different transition classes, hence the dict value is a list
TRANSITIONS = collections.defaultdict(list)

# Set of all Transition classes
TRANSITION_CLASSES = set()

# Ordered list of all state keys
STATE_KEYS = []

# Quaternion componenent names
QUAT_COMPS = ['q1', 'q2', 'q3', 'q4']

# State keys for PCAD-related transitions.  If *any* of these are requested then
# *all* of them need to be processed to get the correct answer.
PCAD_STATE_KEYS = (QUAT_COMPS +
                   ['targ_' + qc for qc in QUAT_COMPS] +
                   ['ra', 'dec', 'roll'] +
                   ['auto_npnt', 'pcad_mode', 'pitch', 'off_nom_roll'])


class NoTransitionsError(ValueError):
    """No transitions found within commands"""
    pass


###################################################################
# Transition base classes
###################################################################

class TransitionMeta(type):
    """
    Metaclass that adds the class to the TRANSITIONS registry.
    """
    def __new__(mcls, name, bases, members):
        cls = super(TransitionMeta, mcls).__new__(mcls, name, bases, members)

        # Register transition classes that have a `state_keys` (base classes do
        # not have this attribute set).
        if hasattr(cls, 'state_keys'):
            for state_key in cls.state_keys:
                if state_key not in STATE_KEYS:
                    STATE_KEYS.append(state_key)
                TRANSITIONS[state_key].append(cls)

            TRANSITION_CLASSES.add(cls)

        return cls


@six.add_metaclass(TransitionMeta)
class BaseTransition(object):
    @classmethod
    def get_state_changing_commands(cls, cmds):
        """
        Get commands that match the required attributes for state changing commands.

        :param cmds: commands (CmdList)

        :returns: subset of ``cmds`` relevant for this Transition class (CmdList)
        """
        # First filter on command attributes.  These
        ok = np.ones(len(cmds), dtype=bool)
        for attr, val in cls.command_attributes.items():
            ok = ok & (cmds[attr] == val)

        out_cmds = cmds[ok]

        # Second do command_params.  Note could use `cmds[attr] == val`for "vectorized"
        # compare, but unrolling the loop here is more efficient since the CmdList class
        # would internally assemble a pure-Python version of the column first.
        if hasattr(cls, 'command_params'):
            ok = np.ones(len(out_cmds), dtype=bool)
            for idx, cmd in enumerate(out_cmds):
                for attr, val in cls.command_params.items():
                    ok[idx] = ok[idx] & (cmd[attr] == val)

            out_cmds = out_cmds[ok]

        return out_cmds


class SingleFixedTransition(BaseTransition):
    @classmethod
    def set_transitions(cls, transitions_dict, cmds):
        """
        Set transitions for a Table of commands ``cmds``.  This is the simplest
        case where there is a single fixed attribute that gets set to a fixed
        value, e.g. pcad_mode='NMAN' for NMM.

        :param transitions_dict: global dict of transitions (updated in-place)
        :param cmds: commands (CmdList)

        :returns: None
        """
        state_cmds = cls.get_state_changing_commands(cmds)
        val = cls.transition_val
        attr = cls.transition_key

        for cmd in state_cmds:
            transitions_dict[cmd['date']][attr] = val


class ParamTransition(BaseTransition):
    @classmethod
    def set_transitions(cls, transitions_dict, cmds):
        """
        Set transitions for a Table of commands ``cmds``.  This is the simplest
        case where there is an attribute that gets set to a specified
        value in the command, e.g. MP_OBSID or SIMTRANS

        :param transitions_dict: global dict of transitions (updated in-place)
        :param cmds: commands (CmdList)

        :returns: None
        """
        state_cmds = cls.get_state_changing_commands(cmds)
        param_key = cls.transition_param_key
        name = cls.transition_key

        for cmd in state_cmds:
            val = dict(REV_PARS_DICT[cmd['idx']])[param_key]
            transitions_dict[cmd['date']][name] = val


###################################################################
# Mech transitions
###################################################################

class HETG_INSR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OHETGIN'}
    state_keys = ['hetg']
    transition_key = 'hetg'
    transition_val = 'INSR'


class HETG_RETR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OHETGRE'}
    state_keys = ['hetg']
    transition_key = 'hetg'
    transition_val = 'RETR'


class LETG_INSR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OLETGIN'}
    state_keys = ['letg']
    transition_key = 'letg'
    transition_val = 'INSR'


class LETG_RETR_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': '4OLETGRE'}
    state_keys = ['letg']
    transition_key = 'letg'
    transition_val = 'RETR'


class SimTscTransition(ParamTransition):
    command_attributes = {'type': 'SIMTRANS'}
    state_keys = ['simpos']
    transition_key = 'simpos'
    transition_param_key = 'pos'


class SimFocusTransition(ParamTransition):
    command_attributes = {'type': 'SIMFOCUS'}
    state_keys = ['simfa_pos']
    transition_key = 'simfa_pos'
    transition_param_key = 'pos'


###################################################################
# OBC etc transitions
###################################################################

class ObsidTransition(ParamTransition):
    command_attributes = {'type': 'MP_OBSID'}
    transition_key = 'obsid'
    state_keys = ['obsid']
    transition_param_key = 'id'


class SPMEnableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AOFUNCEN'}
    command_params = {'aopcadse': 30}

    state_keys = ['sun_pos_mon']
    transition_key = 'sun_pos_mon'
    transition_val = 'ENAB'


class SPMDisableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AOFUNCDS'}
    command_params = {'aopcadsd': 30}

    state_keys = ['sun_pos_mon']
    transition_key = 'sun_pos_mon'
    transition_val = 'DISA'


class SPMEclipseEnableTransition(BaseTransition):
    """
    Automatic enable of sun position monitor which occurs 11 minutes after eclipse exit,
    but only if the battery-connect command occurs within 2:05 minutes of eclipse entry.

    Connect batteries is an event type COMMAND_SW and TLMSID= EOESTECN
    Eclipse entry is event type ORBPOINT with TYPE=PENTRY or TYPE=LSPENTRY
    Eclipse exit is event type ORBPOINT with TYPE=PEXIT or TYPE=LSPEXIT
    """
    state_keys = ['sun_pos_mon']

    @classmethod
    def set_transitions(cls, transitions_dict, cmds):
        """
        Set transitions for a Table of commands ``cmds``.  This is the simplest
        case where there is an attribute that gets set to a specified
        value in the command, e.g. MP_OBSID or SIMTRANS

        :param transitions_dict: global dict of transitions (updated in-place)
        :param cmds: commands (CmdList)

        :returns: None
        """
        # Preselect only commands that might have an impact here.
        ok = (cmds['tlmsid'] == 'EOESTECN') | (cmds['type'] == 'ORBPOINT')
        cmds = cmds[ok]

        connect_time = 0
        connect_flag = False

        for cmd in cmds:
            if cmd['tlmsid'] == 'EOESTECN':
                connect_time = DateTime(cmd['date']).secs

            elif cmd['type'] == 'ORBPOINT':
                if cmd['event_type'] in ('PENTRY', 'LSPENTRY'):
                    entry_time = DateTime(cmd['date']).secs
                    connect_flag = (entry_time - connect_time < 125)

                elif cmd['event_type'] in ('PEXIT', 'LSPEXIT') and connect_flag:
                    scs33 = DateTime(cmd['date']) + 11 * 60 / 86400  # 11 minutes in days
                    transitions_dict[scs33.date]['sun_pos_mon'] = 'ENAB'
                    connect_flag = False


###################################################################
# PCAD transitions
###################################################################

class DitherEnableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AOENDITH'}
    state_keys = ['dither']
    transition_key = 'dither'
    transition_val = 'ENAB'


class DitherDisableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AODSDITH'}
    state_keys = ['dither']
    transition_key = 'dither'
    transition_val = 'DISA'


class DitherParamsTransition(BaseTransition):
    command_attributes = {'type': 'MP_DITHER',
                          'tlmsid': 'AODITPAR'}
    state_keys = ['dither_phase_pitch', 'dither_phase_yaw',
                  'dither_ampl_pitch', 'dither_ampl_yaw',
                  'dither_period_pitch', 'dither_period_yaw']

    @classmethod
    def set_transitions(cls, transitions_dict, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)

        for cmd in state_cmds:
            dither = {'dither_phase_pitch': np.degrees(cmd['angp']),
                      'dither_phase_yaw': np.degrees(cmd['angy']),
                      'dither_ampl_pitch': np.degrees(cmd['coefp']) * 3600,
                      'dither_ampl_yaw': np.degrees(cmd['coefy']) * 3600,
                      'dither_period_pitch': 2 * np.pi / cmd['ratep'],
                      'dither_period_yaw': 2 * np.pi / cmd['ratey']}
            transitions_dict[cmd['date']].update(dither)


class NMM_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONMMODE'}
    state_keys = PCAD_STATE_KEYS
    transition_key = 'pcad_mode'
    transition_val = 'NMAN'


class NPM_Transition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONPMODE'}
    state_keys = PCAD_STATE_KEYS
    transition_key = 'pcad_mode'
    transition_val = 'NPNT'


class AutoNPMEnableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONM2NPE'}
    state_keys = PCAD_STATE_KEYS
    transition_key = 'auto_npnt'
    transition_val = 'ENAB'


class AutoNPMDisableTransition(SingleFixedTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONM2NPD'}
    state_keys = PCAD_STATE_KEYS
    transition_key = 'auto_npnt'
    transition_val = 'DISA'


class TargQuatTransition(BaseTransition):
    command_attributes = {'type': 'MP_TARGQUAT'}
    state_keys = PCAD_STATE_KEYS

    @classmethod
    def set_transitions(cls, transitions, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)

        for cmd in state_cmds:
            transition = transitions[cmd['date']]
            for qc in ('q1', 'q2', 'q3', 'q4'):
                transition['targ_' + qc] = cmd[qc]


class ManeuverTransition(BaseTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AOMANUVR'}
    state_keys = PCAD_STATE_KEYS

    @classmethod
    def set_transitions(cls, transitions, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)

        for cmd in state_cmds:
            # Note that the transition key 'maneuver' doesn't really matter here
            # as long as it is different from the other state keys.
            transitions[cmd['date']]['maneuver'] = {'func': cls.add_transitions,
                                                    'cmd': cmd}

    @classmethod
    def add_transitions(cls, date, transitions, state, idx, cmd):
        end_manvr_date = cls.add_manvr_transitions(date, transitions, state, idx, cmd)

        # If auto-transition to NPM after manvr is enabled (this is
        # normally the case) then back to NPNT at end of maneuver
        if state['auto_npnt'] == 'ENAB':
            transition = {'date': end_manvr_date, 'pcad_mode': 'NPNT'}
            add_transition(transitions, idx, transition)

    @classmethod
    def add_manvr_transitions(cls, date, transitions, state, idx, cmd):
        # Get the current target attitude state
        targ_att = [state['targ_' + qc] for qc in QUAT_COMPS]

        # Deal with startup transient where spacecraft attitude is not known.
        # In this case first maneuver is a bogus null maneuver.
        if state['q1'] is None:
            for qc in QUAT_COMPS:
                state[qc] = state['targ_' + qc]

        # Get current spacecraft attitude
        curr_att = [state[qc] for qc in QUAT_COMPS]

        # Get attitudes for the maneuver at about 5-minute intervals.
        atts = Chandra.Maneuver.attitudes(curr_att, targ_att,
                                          tstart=DateTime(cmd['date']).secs)

        # Compute pitch and off-nominal roll at the midpoint of each interval, except
        # also include the exact last attitude.
        pitches = np.hstack([(atts[:-1].pitch + atts[1:].pitch) / 2,
                             atts[-1].pitch])
        off_nom_rolls = np.hstack([(atts[:-1].off_nom_roll + atts[1:].off_nom_roll) / 2,
                                   atts[-1].off_nom_roll])

        # Add transitions for each bit of the maneuver.  Note that this sets the attitude
        # (q1..q4) at the *beginning* of each state, while setting pitch and
        # off_nominal_roll at the *midpoint* of each state.  This is for legacy
        # compatibility with Chandra.cmd_states but might be something to change since it
        # would probably be better to have the midpoint attitude.
        for att, pitch, off_nom_roll in zip(atts, pitches, off_nom_rolls):
            date = DateTime(att.time).date
            transition = {'date': date}
            for qc in QUAT_COMPS:
                transition[qc] = att[qc]
            transition['pitch'] = pitch
            transition['off_nom_roll'] = off_nom_roll

            q_att = Quat([att[x] for x in QUAT_COMPS])
            transition['ra'] = q_att.ra
            transition['dec'] = q_att.dec
            transition['roll'] = q_att.roll

            add_transition(transitions, idx, transition)

        return date  # Date of end of maneuver.


class NormalSunTransition(ManeuverTransition):
    command_attributes = {'type': 'COMMAND_SW',
                          'tlmsid': 'AONSMSAF'}
    state_keys = PCAD_STATE_KEYS

    @classmethod
    def add_transitions(cls, date, transitions, state, idx, cmd):
        # Transition to NSUN
        state['pcad_mode'] = 'NSUN'

        # Setup for maneuver to sun-pointed attitude from current att
        curr_att = [state[qc] for qc in QUAT_COMPS]
        targ_att = Chandra.Maneuver.NSM_attitude(curr_att, cmd['date'])
        for qc, targ_q in zip(QUAT_COMPS, targ_att.q):
            state['targ_' + qc] = targ_q

        # Do the maneuver
        cls.add_manvr_transitions(date, transitions, state, idx, cmd)


###################################################################
# ACIS transitions
###################################################################

class ACISTransition(BaseTransition):
    command_attributes = {'type': 'ACISPKT'}
    state_keys = ['clocking', 'power_cmd', 'vid_board', 'fep_count', 'si_mode', 'ccd_count']

    @classmethod
    def set_transitions(cls, transitions, cmds):
        state_cmds = cls.get_state_changing_commands(cmds)
        for cmd in state_cmds:
            tlmsid = cmd['tlmsid']
            date = cmd['date']

            if tlmsid.startswith('WSPOW'):
                pwr = decode_power(tlmsid)
                transitions[date].update(fep_count=pwr['fep_count'],
                                         ccd_count=pwr['ccd_count'],
                                         vid_board=pwr['vid_board'],
                                         clocking=pwr['clocking'],
                                         power_cmd=tlmsid)

            elif tlmsid in ('XCZ0000005', 'XTZ0000005'):
                transitions[date].update(clocking=1, power_cmd=tlmsid)

            elif tlmsid == 'WSVIDALLDN':
                transitions[date].update(vid_board=0, power_cmd=tlmsid)

            elif tlmsid == 'AA00000000':
                transitions[date].update(clocking=0, power_cmd=tlmsid)

            elif tlmsid == 'WSFEPALLUP':
                transitions[date].update(fep_count=6, power_cmd=tlmsid)

            elif tlmsid.startswith('WC'):
                transitions[date].update(si_mode='CC_' + tlmsid[2:7])

            elif tlmsid.startswith('WT'):
                transitions[date].update(si_mode='TE_' + tlmsid[2:7])


###################################################################
# State transitions processing code
###################################################################

def get_transition_classes(state_keys=None):
    """
    Get all BaseTransition subclasses in this module corresponding to
    state keys ``state_keys``.
    """
    if isinstance(state_keys, six.string_types):
        state_keys = [state_keys]

    if state_keys is None:
        # itertools.chain => concat list of lists
        trans_classes = set(itertools.chain.from_iterable(TRANSITIONS.values()))
    else:
        trans_classes = set(itertools.chain.from_iterable(
                classes for state_key, classes in TRANSITIONS.items()
                if state_key in state_keys))
    return trans_classes


def get_transitions_list(cmds, state_keys=None):
    """
    For given set of commands ``cmds`` and ``state_keys``, return a list of
    transitions.

    A ``transition`` here defines a state transition.  It is a dict with a ``date`` key
    (date of transition) and key/value pairs corresponding to the state keys that change.

    If ``state_keys`` is None then all known state keys are included.

    :param cmds: CmdList with spacecraft commands
    :param state_keys: desired state keys (None, str, or list)

    :returns: list of dict (transitions)
    """
    # To start, collect transitions in a dict keyed by date.  This auto-initializes
    # a dict whenever a new date is used, allowing (e.g.) a single step of::
    #
    #   transitions_dict['2017:002:01:02:03.456']['obsid'] = 23456.
    transitions_dict = collections.defaultdict(dict)

    # Iterate through Transition classes which depend on or affect ``state_keys``
    # and ask each one to update ``transitions_dict`` in-place to include
    # transitions from that class.
    for transition_class in get_transition_classes(state_keys):
        transition_class.set_transitions(transitions_dict, cmds)

    # Convert the dict of transitions (keyed by date) into an ordered list of transitions
    # sorted by date.  A *list* of transitions is needed to allow a transition to
    # dynamically generate additional (later) transitions, e.g. in the case of a maneuver.
    transitions_list = []
    for date in sorted(transitions_dict):
        transition = transitions_dict[date]
        transition['date'] = date
        transitions_list.append(transition)

    # In the rest of this module ``transitions`` is always this *list* of transitions.
    return transitions_list


def add_sun_vector_transitions(start, stop, transitions):
    """
    Add transitions between start/stop every 10ksec to sample the pitch and off_nominal
    roll during NPNT.  These are function transitions which check to see that
    pcad_mode == 'NPNT' before changing the pitch / off_nominal_roll.

    This function gets as a special-case within get_states_for_cmds() after assembling the
    initial list of transitions that are generated from Transition classes.

    :param start: start date for sun vector transitions (DateTime compatible)
    :param stop: stop date for sun vector transitions (DateTime compatible)
    :param transitions: global list of transitions (updated in-place)

    :returns: None
    """
    # np.floor is used here to get 'times' at even increments of "sample_time"
    # so that the commands will be at the same times in an interval even
    # if a different time range is being updated.
    sample_time = 10000
    tstart = np.floor(DateTime(start).secs / sample_time) * sample_time
    tstop = DateTime(stop).secs
    times = np.arange(tstart, tstop, sample_time)
    dates = DateTime(times).date

    # Now with the dates, finally make all the transition dicts which will
    # call `update_pitch_state` during state processing.
    pitch_transitions = [{'date': date,
                          'update_pitch': {'func': update_sun_vector_state}}
                         for date in dates]

    # Add to the transitions list and sort by date.  Normally one would use the
    # add_transition() function, but in this case there are enough transitions
    # that just tossing them on the end and re-sorting is better.
    transitions.extend(pitch_transitions)
    transitions.sort(key=lambda x: x['date'])


def update_sun_vector_state(date, transitions, state, idx):
    """
    This function gets called during state processing to potentially update the
    ``pitch`` and ``off_nominal`` states if pcad_mode is NPNT.

    :param date: date (str)
    :param transitions: global list of transitions
    :param state: current state (dict)
    :param idx: current index into transitions
    """
    if state['pcad_mode'] == 'NPNT':
        q_att = Quat([state[qc] for qc in QUAT_COMPS])
        state['pitch'] = Ska.Sun.pitch(q_att.ra, q_att.dec, date)
        state['off_nom_roll'] = Ska.Sun.off_nominal_roll(q_att, date)


def add_transition(transitions, idx, transition):
    """
    Add ``transition`` to the ``transitions`` list at the first appropriate
    place after the ``idx`` entry.

    This is typically used by dynamic transitions that are actually calling a function to
    generate downstream transitions.  The ManeuverTransition class is the canonical
    example.

    :param transitions: global list of transition dicts
    :param idx: current index into transitions in state processing
    :param transition: transition to add (dict)

    :returns: None
    """
    # Prevent adding command before current command since the command
    # interpreter is a one-pass process.
    date = transition['date']
    if date < transitions[idx]['date']:
        raise ValueError('cannot insert transition prior to current command')

    # Insert transition at first place where new transition date is strictly
    # less than existing transition date.  This implementation is linear, and
    # could be improved, though in practice transitions are often inserted
    # close to the original.
    for ii in range(idx + 1, len(transitions)):
        if date < transitions[ii]['date']:
            transitions.insert(ii, transition)
            break
    else:
        transitions.append(transition)


def get_states_for_cmds(cmds, state_keys=None, state0=None):
    """
    Get table of states corresponding to intervals when ``state_keys`` parameters
    are unchanged given the input commands ``cmds``.

    If ``state_keys`` is None then all known state keys are included.

    The output table will contain columns for ``state_keys`` along with ``datestart`` and
    ``datestop`` columns.  It may also include additional columns for corresponding
    dependent states.  For instance in order to compute the attitude quaternion state
    ``q1`` it is necessary to collect a number of other states such as ``pcad_mode`` and
    target quaternions ``targ_q1`` through ``targ_q4``.  This function returns all these.
    One can call the ``reduce_states()`` function to reduce to only the desired state
    keys.

    :param cmds: input commands (CmdList)
    :param state_keys: state keys of interest

    :returns: astropy Table of states
    """
    # Define complete list of column names for output table corresponding to
    # each state key.  Maintain original order and uniqueness of keys.
    if state_keys is None:
        state_keys = STATE_KEYS
        orig_state_keys = state_keys
    else:
        # Go through each transition class which impacts desired state keys and accumulate
        # all the state keys that the classes touch.  For instance if user requests
        # state_keys=['q1'] then we actually need to process all the PCAD_states state keys
        # and then at the end reduce down to the requested keys.
        orig_state_keys = state_keys
        state_keys = []
        for state_key in orig_state_keys:
            for cls in TRANSITION_CLASSES:
                if state_key in cls.state_keys:
                    state_keys.extend(cls.state_keys)
        state_keys = _unique(state_keys)

    # Get transitions, which is a list of dict (state key
    # and new state value at that date).  This goes through each active
    # transition class and accumulates transitions.
    transitions = get_transitions_list(cmds, state_keys)

    # See add_sun_vec_transitions() for explanation.  IDEALLY: make this happen
    # more naturally within Transitions class machinery.
    if 'pitch' in state_keys or 'off_nominal_roll' in state_keys:
        add_sun_vector_transitions(cmds[0]['date'], cmds[-1]['date'], transitions)

    # List of dict to hold state values.  Datestarts is the corresponding list of
    # start dates for each state.
    states = [{key: None for key in state_keys}]

    try:
        datestarts = [transitions[0]['date']]
    except IndexError:
        raise NoTransitionsError('no transitions for state keys {} in cmds'
                                 .format(state_keys))

    # Apply initial ``state0`` values if available
    if state0:
        for key, val in state0.items():
            if key in state_keys:
                states[0][key] = val
            else:
                warnings.warn('state0 key {} is not in state_keys, ignoring it'.format(key))

    # Do main state transition processing.  Start by making current ``state`` which is a
    # reference the last state in the list.
    state = states[0]

    for idx, transition in enumerate(transitions):
        date = transition['date']

        # If transition is at a new date from current state then break the current state
        # and make a new one (as a copy of current).  Note that multiple transitions can
        # be at the same date (from commanding at same date), though that is not the usual
        # case.
        if date != datestarts[-1]:
            state = state.copy()
            states.append(state)
            datestarts.append(date)

        # Process the transition.
        for key, value in transition.items():
            if isinstance(value, dict):
                # Special case of a functional transition that calls a function
                # instead of directly updating the state.  The function might itself
                # update the state or it might generate downstream transitions.
                func = value.pop('func')
                func(date, transitions, state, idx, **value)
            elif key != 'date':
                # Normal case of just updating current state
                state[key] = value

    # Make into an astropy Table and set up datestart/stop columns
    states = Table(rows=states, names=state_keys)
    states.add_column(Column(datestarts, name='datestart'), 0)
    # Add datestop which is just the previous datestart.
    datestop = states['datestart'].copy()
    datestop[:-1] = states['datestart'][1:]
    # Final datestop far in the future
    datestop[-1] = '2099:365:00:00:00.000'
    states.add_column(Column(datestop, name='datestop'), 1)

    return states


def reduce_states(states, state_keys):
    """
    Reduce ``states`` table to have transitions *only* in the ``state_keys`` list.

    :param states: states Table or numpy recarray
    :param state_keys: list of desired state keys

    :returns: reduced states (astropy Table)
    """

    # TODO: this fails for a states column with no transitions

    if not isinstance(states, Table):
        states = Table(states)

    different = np.zeros(len(states), dtype=bool)
    for key in state_keys:
        col = states[key]
        different[1:] |= (col[:-1] != col[1:])

    out = states[['datestart', 'datestop'] + state_keys][different]
    out['datestop'][:-1] = out['datestart'][1:]

    return out


def get_state0(date=None, state_keys=None, lookbacks=(7, 30, 180, 1000)):
    """
    Get the state at ``date`` for ``state_keys``.

    This function finds the state at a particular date by fetching commands
    prior to that date and determine the states.  Since some state keys
    like ``pitch`` change often (many times per day) while others like ``letg``
    may not change for weeks, this function does dynamic lookbacks from ``date``
    to find transitions for each key.  By default it will try looking back
    7 days, then 30 days, then 180 days, and finally 1000 days.  This lookback
    sequence can be controlled with the ``lookbacks`` argument.

    If ``state_keys`` is None then all available states are returned.

    :param date: date (DateTime compatible, default=NOW)
    :param state_keys: list of state keys or None
    :param lookbacks: list of lookback times in days (default=[7, 30, 180, 1000])

    :returns: dict of state key/value pairs
    """
    lookbacks = sorted(lookbacks)
    stop = DateTime(date)
    if state_keys is None:
        state_keys = STATE_KEYS

    state0 = {}

    for lookback in lookbacks:
        cmds = commands.filter(stop - lookback, stop)

        for state_key in state_keys:
            # Don't bother if we already have a value for this key.
            if state_key in state0:
                continue

            # Get available commanded states for this particular state_key.  This may
            # return state values for many more keys (e.g. PCAD-related), and some or all
            # of these might be None if the relevant command never happened.  Fill in
            # state0 as possible from last state (corresponding to the state after the
            # last command in cmds).
            try:
                states = get_states_for_cmds(cmds, [state_key])
            except NoTransitionsError:
                # No transitions within `cmds` for state_key, continue with other keys
                continue

            colnames = set(states.colnames) - set(['datestart', 'datestop'])
            for colname in colnames:
                if states[colname][-1] is not None:
                    state0[colname] = states[colname][-1]

        # If we have filled in state0 for every key then we're done.
        # Otherwise bump the lookback and try again.
        if all(state_key in state0 for state_key in state_keys):
            break
    else:
        # Didn't find all state keys
        missing_keys = set(state_keys) - set(state0)

        # Try to get defaults from transition classes
        for missing_key in missing_keys:
            for cls in get_transition_classes(missing_key):
                if hasattr(cls, 'default_value'):
                    state0[missing_key] = cls.default_value

        # Try again...
        missing_keys = set(state_keys) - set(state0)
        if missing_keys:
            raise ValueError('did not find transitions for state key(s)'
                             ' {} within {} days of {}.  Maybe adjust the `lookbacks` argument?'
                             .format(missing_keys, lookbacks[-1], stop.date))

    return state0


def _unique(seq):
    """Return unique elements of ``seq`` in order"""
    seen = set()
    seen_add = seen.add
    return [x for x in seq if not (x in seen or seen_add(x))]
