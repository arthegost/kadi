"""Update the events database"""

import re
import types
import argparse

import numpy as np
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction

import pyyaks.logger
from Chandra.Time import DateTime

from . import models

logger = None  # for pyflakes


def get_opt(args=None):
    parser = argparse.ArgumentParser(description='Update the events database')
    parser.add_argument("--date-now",
                        default=DateTime().date,
                        help="Set effective processing date for testing (default=NOW)")
    parser.add_argument("--date-start",
                        default=None,
                        help=("Processing start date (loops by max-lookback-time "
                              "until date-now if set)"))
    parser.add_argument("--log-level",
                        default=pyyaks.logger.VERBOSE,
                        help=("Logging level"))
    parser.add_argument("--model",
                        action='append',
                        dest='models',
                        help="Model name to process [match regex] (default = all)")

    args = parser.parse_args(args)
    return args


def update(EventModel, date_now):
    date_now = DateTime(date_now)
    name = EventModel.name
    logger.info('Updating {} events to {}'.format(name, date_now.date))

    try:
        update = models.Update.objects.get(name=name)
        date_start = DateTime(update.date)
        update.date = date_now.date
    except ObjectDoesNotExist:
        logger.info('No previous update for {} found'.format(name))
        update = models.Update(name=name, date=date_now.date)
        date_start = date_now

    # Get events for this model from telemetry.  This is returned as a list
    # of dicts with key/val pairs corresponding to model fields
    events = EventModel.get_events(date_start - EventModel.lookback, date_now)

    with transaction.commit_on_success():
        for event in events:
            # Check if event is already in database
            try:
                event_model = EventModel.objects.get(start=event['start'])
                logger.verbose('Skipping {} at {}: already in database'
                               .format(name, event['start']))
                continue
            except ObjectDoesNotExist:
                pass  # add the event

            event_model = EventModel.from_dict(event, logger)
            logger.info('Adding {} {}'.format(name, event_model))
            event_model.save()

            # Add any foreign rows (many to one)
            for class_name, rows in event.get('foreign', {}).items():
                ForeignModel = getattr(models, class_name)
                if isinstance(rows, np.ndarray):
                    rows = [{key: row[key].tolist() for key in row.dtype.names} for row in rows]
                for row in rows:
                    # Convert to a plain dict if row is structured array
                    foreign_model = ForeignModel.from_dict(row, logger)
                    setattr(foreign_model, name, event_model)
                    logger.verbose('Adding {}'.format(foreign_model))
                    foreign_model.save()

    # If processing got here with no exceptions then save the event update
    # information to database
    update.save()


def main():
    global logger

    opt = get_opt()
    logger = pyyaks.logger.get_logger(name='events', level=opt.log_level,
                                      format="%(asctime)s %(message)s")

    # Allow for a cmd line option --date-start.  If supplied then loop the
    # effective value of opt.date_now from date_start to the cmd line
    # --date-now in steps of --max-lookback-time

    if opt.date_start is None:
        date_nows = [opt.date_now]
    else:
        t_starts = np.arange(DateTime(opt.date_start).secs,
                             DateTime(opt.date_now).secs,
                             30 * 86400.)
        date_nows = [DateTime(t).date for t in t_starts]
        date_nows.append(opt.date_now)

    # Get the event classes in models module
    EventModels = [val for name, val in vars(models).items()
                   if (isinstance(val, (type, types.ClassType))  # is a class
                       and issubclass(val, models.Event)  # is an Event subclass
                       and hasattr(val, 'name')  # is not a base class
                       )]

    if opt.models:
        EventModels = [x for x in EventModels
                       if any(re.match(y, x.name) for y in opt.models)]

    for EventModel in EventModels:
        for date_now in date_nows:
            update(EventModel, date_now)

if __name__ == '__main__':
    main()
