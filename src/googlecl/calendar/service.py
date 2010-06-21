# Copyright (C) 2010 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


"""Service details and instances for the Picasa service.

Some use cases:
Add event:
  calendar add "Lunch with Tony on Tuesday at 12:00" 

List events for today:
  calendar today

"""
__author__ = 'tom.h.miller@gmail.com (Tom Miller)'
import datetime
import gdata.calendar.service
import googlecl
import googlecl.service
import urllib
from googlecl.calendar import SECTION_HEADER


USER_BATCH_URL_FORMAT = \
               gdata.calendar.service.DEFAULT_BATCH_URL.replace('default', '%s')
QUERY_DATE_FORMAT = '%Y-%m-%dT%H:%S:%M'

class CalendarError(googlecl.service.Error):
  """Base error for Calendar errors."""
  pass

class EventsNotFound(CalendarError):
  """No events matching given parameters were found."""
  pass


class Calendar():
  
  """Wrapper class for some calendar entry data."""

  def __init__(self, cal_entry=None, user=None, name=None):
    """Parse a CalendarEntry into "user" and human-readable names,
       or take them directly."""
    if cal_entry:
      # Non-primary calendar feeds look like this:
      # http:blah/.../feeds/JUNK%40group.calendar.google.com/private/full
      # So grab the part after /feeds/ and unquote it.
      self.user = urllib.unquote(cal_entry.content.src.split('/')[-3])
      self.name = cal_entry.title.text
    else:
      self.user = user
      self.name = name

  def __str__(self):
    return self.name


class CalendarServiceCL(gdata.calendar.service.CalendarService,
                        googlecl.service.BaseServiceCL):

  """Extends gdata.calendar.service.CalendarService for the command line.

  This class adds some features focused on using Calendar via an installed
  app with a command line interface.

  """

  def __init__(self, regex=False, tags_prompt=False, delete_prompt=True):
    """Constructor.
    
    Keyword arguments:
      regex: Indicates if regular expressions should be used for matching
             strings, such as event titles. (Default False)
      tags_prompt: Indicates if while inserting events, instance should prompt
                   for tags for each photo. (Default False)
      delete_prompt: Indicates if instance should prompt user before
                     deleting a calendar or event. (Default True)
              
    """
    gdata.calendar.service.CalendarService.__init__(self)
    googlecl.service.BaseServiceCL._set_params(self, regex,
                                               tags_prompt, delete_prompt)

  def _batch_delete_recur(self, event, cal_user,
                          start_date=None, end_date=None):
    """Delete a subset of instances of recurring events."""
    request_feed = gdata.calendar.CalendarEventFeed()
    single_events = self.get_events(cal_user, start_date=start_date,
                                    end_date=end_date,
                                    title=event.title.text,
                                    expand_recurrence=True)
    delete_events = [e for e in single_events if e.original_event and
                     e.original_event.id == event.id.text.split('/')[-1]]
    if not delete_events:
      raise EventsNotFound
    map(request_feed.AddDelete, [None], delete_events, [None])
    self.ExecuteBatch(request_feed, USER_BATCH_URL_FORMAT % cal_user)

  def delete_events(self, events, date, calendar_user):
    """Delete events from a calendar.
    
    Keyword arguments:
      events: List of non-expanded calendar events to delete.
      date: Date string specifying the date range of the events, as the date
            option.
      calendar_user: "User" of the calendar to delete events from.
    
    """
    single_events = [e for e in events if not e.recurrence and
                     e.event_status.value != 'CANCELED']
    recurring_events = [e for e in events if e.recurrence and e.when]
    # Not sure which is faster/better: above approach, or using set subtraction
    # recurring_events = set(events) - set(single_events)
    if not single_events and not recurring_events:
      raise EventsNotFound
    delete_default = googlecl.CONFIG.getboolean('GENERAL', 'delete_by_default')
    self.Delete(single_events, 'event', delete_default)
    
    start_date, end_date, start_date_utc, end_date_utc = get_start_and_end(date)
    # option_list is a list of tuples, (prompt_string, deletion_instruction)
    # prompt_string gets displayed to the user,
    # deletion_instruction is a special value that will let the program know
    #   what to do.
    #     'ALL' -- delete all events in the series.
    #     'NONE' -- don't delete anything.
    #     'TWIXT' -- delete events between start_date and end_date.
    #     'ON' -- delete events on the single date given.
    #     'ONAFTER' -- delete events on and after the date given.
    option_list = [('All events in this series', 'ALL')]
    if start_date and end_date:
      option_list.append(('Instances between ' + start_date + ' and ' +
                          end_date, 'TWIXT'))
    elif start_date or end_date:
      if (start_date and not start_date_utc) or (end_date and not end_date_utc):
        raise CalendarError('UTC date not set when TZ date is!')
      delete_date = (start_date or end_date)
      delete_date_utc = (start_date_utc or end_date_utc)
      option_list.append(('Instances on ' + delete_date,
                          'ON'))
      option_list.append(('All events on and after ' + delete_date,
                          'ONAFTER'))
    option_list.append(('Do not delete', 'NONE'))
    prompt_str = ''
    for i, option in enumerate(option_list):
      prompt_str += str(i) + ') ' + option[0] + '\n' 
    for event in recurring_events:
      if self.prompt_for_delete:
        delete_selection = -1
        while delete_selection < 0 or delete_selection > len(option_list)-1:
          delete_selection = int(raw_input('Delete "%s"?\n%s' % 
                                           (event.title.text, prompt_str)))
        option = option_list[delete_selection]
        if option[1] == 'ALL':
          gdata.service.GDataService.Delete(self, event.GetEditLink().href)
        elif option[1] == 'TWIXT':
          self._batch_delete_recur(event, calendar_user,
                                   start_date=start_date_utc,
                                   end_date=end_date_utc)
        elif option[1] == 'ON':
          start_date_utc, end_date_utc = _tomorrowize(delete_date_utc)
          self._batch_delete_recur(event, calendar_user,
                                   start_date=start_date_utc,
                                   end_date=end_date_utc)
        elif option[1] == 'ONAFTER':
          self._batch_delete_recur(event, calendar_user,
                                   start_date=delete_date_utc)
        elif option[1] != 'NONE':
          raise CalendarError('Got unexpected batch deletion command!')

      else:
        gdata.service.GDataService.Delete(self, event.GetEditLink().href)

  DeleteEvents = delete_events

  def quick_add_event(self, quick_add_strings, calendar_user):
    """Add an event using the Calendar Quick Add feature.
    
    Keyword arguments:
      quick_add_strings: List of strings to be parsed by the Calendar service,
                         as if it was entered via the "Quick Add" function.
      calendar_user: "User" of the calendar to add to.
    
    Returns:
      The event that was added, or None if the event was not added. 
    
    """
    import atom
    request_feed = gdata.calendar.CalendarEventFeed()
    for i, event_str in enumerate(quick_add_strings):
      event = gdata.calendar.CalendarEventEntry()
      event.content = atom.Content(text=event_str)
      event.quick_add = gdata.calendar.QuickAdd(value='true')
      request_feed.AddInsert(event, 'insert-request' + str(i))
    response_feed = self.ExecuteBatch(request_feed,
                                      USER_BATCH_URL_FORMAT % calendar_user)
    return response_feed.entry

  QuickAddEvent = quick_add_event

  def get_calendar_user_list(self, cal_name=None):
    """Get "user" name and human-readable name for one or more calendars.
    
    The "user" for a calendar is an awful misnomer for the ID for the calendar.
    To get events for a calendar, you can form a query with
      cal_list = self.get_calendar_user_list('my calendar name')
      if cal_list:
        query = gdata.calendar.CalendarEventQuery(user=cal_list[0].user)
    
    Keyword arguments:
      cal_name: Name of the calendar to match. Default None to return the 
                an instance representing only the default / main calendar.
      
    Returns:
      A list of Calendar instances, or None of there were no matches
      for cal_name.
    
    """
    if not cal_name:
      return [Calendar(user='default', name=self.email)]
    else:
      cal_list = self.GetEntries('/calendar/feeds/default/allcalendars/full',
                                 title=cal_name,
                          converter=gdata.calendar.CalendarListFeedFromString)
      if cal_list:
        return [Calendar(cal) for cal in cal_list]
    return None

  GetCalendarUserList = get_calendar_user_list

  def get_events(self, calendar_user, start_date=None, end_date=None,
                 title=None, query=None, max_results=1000,
                 expand_recurrence=True):
    """Get events.
    
    Keyword arguments:
      calendar_user: "user" of the calendar to get events for.
                     See get_calendar_user_list.
      start_date: Start date of the event(s). Must follow the RFC 3339
                  timestamp format and be in UTC. Default None.
      end_date: End date of the event(s). Must follow the RFC 3339 timestamp
                format and be in UTC. Default None.
      title: Title to look for in the event, supporting regular expressions.
             Default None for any title.
      query: Query string (not encoded) for doing full-text searches on event
             titles and content.
      max_results: Maximum number of events to get. Default 100.
      expand_recurrence: If true, expand recurring events per the 'singleevents'
                         query parameter. Otherwise, don't.
    
    Returns:
      List of events from primary calendar that match the given params.
                  
    """
    query = gdata.calendar.service.CalendarEventQuery(user=calendar_user,
                                                      text_query=query)
    if start_date:
      query.start_min = start_date
    if end_date:
      query.start_max = end_date
    if expand_recurrence:
      query.singleevents = 'true'
    query.orderby = 'starttime'
    query.sortorder = 'ascend'
    query.max_results = max_results
    return self.GetEntries(query.ToUri(), title,
                           converter=gdata.calendar.CalendarEventFeedFromString)

  GetEvents = get_events

  def is_token_valid(self, test_uri='/calendar/feeds/default/private/full'):
    """Check that the token being used is valid."""
    return googlecl.service.BaseServiceCL.IsTokenValid(self, test_uri)

  IsTokenValid = is_token_valid


SERVICE_CLASS = CalendarServiceCL


def get_datetimes(cal_entry):
  """Get datetime objects for the start and end of the event specified by a
  calendar entry.
  
  Keyword arguments:
    cal_entry: A CalendarEventEntry.
  
  Returns:
    (start_time, end_time, freq) where
      start_time - datetime object of the start of the event.
      end_time - datetime object of the end of the event.
      freq - string that tells how often the event repeats (NoneType if the
           event does not repeat (does not have a gd:recurrence element)).
  
  """
  import time
  if cal_entry.recurrence:
    return parse_recurrence(cal_entry.recurrence.text)
  else:
    freq = None
    when = cal_entry.when[0]
    try:
      start_time_data = time.strptime(when.start_time[:-10],
                                      '%Y-%m-%dT%H:%M:%S')
      end_time_data = time.strptime(when.end_time[:-10],
                                    '%Y-%m-%dT%H:%M:%S')
    except ValueError:
      # Try to handle date format for all-day events
      start_time_data = time.strptime(when.start_time, '%Y-%m-%d')
      end_time_data = time.strptime(when.end_time, '%Y-%m-%d')
  return (start_time_data, end_time_data, freq)


def get_start_and_end(date):
  """Split a string representation of a date or range of dates.
  
  Ranges should be designated via a comma. For example, '2010-06-01,2010-06-20'
  will set return ('2010-06-01', '2010-06-20', ...)
  
  Returns:
    Tuple of (start, end, utc_start, utc_end) where
       start is either the starting date or None,
       end is either the ending date or None,
       utc_start is the starting date shifted into UTC,
       utc_end is the ending date shifted into UTC.
  
  """
  if date and date != ',':
    # Partition won't choke on date == '2010-06-05', split will.
    start, is_range, end = date.partition(',')
  else:
    # If no date is given, set a start of today.
    start = datetime.datetime.today().strftime(googlecl.service.DATE_FORMAT)
    is_range = None
    end = None
  utc_timedelta = get_utc_timedelta()
  # Even though the "when" elements of events will be properly shifted into
  # the user's timezone, all queries are interpreted as UTC (GMT) time.
  if start:
    start_time = datetime.datetime.strptime(start, googlecl.service.DATE_FORMAT)
    utc_start = (start_time + (utc_timedelta)).strftime(QUERY_DATE_FORMAT)
  else:
    utc_start = None
  if not is_range:
    dates = _tomorrowize(start)
    # _tomorrowize() returns a full timestamp with hour data, so trim
    # down to same format that user enters dates in.
    end = dates[1][:10]
  if end:
    end_time = datetime.datetime.strptime(end, googlecl.service.DATE_FORMAT)
    utc_end = (end_time + (utc_timedelta)).strftime(QUERY_DATE_FORMAT)
  else:
    utc_end = None
  return (start, end, utc_start, utc_end)


def get_utc_timedelta():
  """Return the UTC offset as a timedelta."""
  import time
  if time.daylight != 0:
    return datetime.timedelta(hours=time.altzone/3600)
  else:
    return datetime.timedelta(hours=time.timezone/3600)


def parse_recurrence(time_string):
  """Parse recurrence data found in event entry.
  
  Keyword arguments:
    time_string: Value of entry's recurrence.text field.
  
  Returns:
    Tuple of (start_time, end_time, frequency). All values are in the user's
    current timezone (I hope). start_time and end_time are datetime objects,
    and frequency is a dictionary mapping RFC 2445 RRULE parameters to their
    values. (http://www.ietf.org/rfc/rfc2445.txt, section 4.3.10)
  
  """
  import time
  # Google calendars uses a pretty limited section of RFC 2445, and I'm
  # abusing that here. This will probably break if Google ever changes how
  # they handle recurrence, or how the recurrence string is built.
  data = time_string.split('\n')
  start_time_string = data[0].split(':')[-1]
  start_time = time.strptime(start_time_string,'%Y%m%dT%H%M%S')
  
  end_time_string = data[1].split(':')[-1]
  end_time = time.strptime(end_time_string,'%Y%m%dT%H%M%S')
  
  freq_string = data[2][6:]
  freq_properties = freq_string.split(';')
  freq = {}
  for prop in freq_properties:
    key, value = prop.split('=')
    freq[key] = value
  return (start_time, end_time, freq)


def _tomorrowize(date=None):
  """Return a date range from given date until tomorrow.
  
  Keyword arguments:
    date: String of date to start at, following RFC 3339 timestamp format,
          but does not have to include data past 'YYYY-MM-DD'.
          Must be in UTC. Default None, for today.
    
  Returns:
    (start_date, end_date) where both dates are strings representing UTC time
    in the RFC 3339 format. end_date is exactly one day after start_date.
    
  """
  if not date:
    date_data = datetime.datetime.today()
  else:
    try:
      date_data = datetime.datetime.strptime(date, QUERY_DATE_FORMAT)
    except ValueError:
      # If there is no hour data (i.e. the DATE_FORMAT succeeds), add it.
      date_data = datetime.datetime.strptime(date, googlecl.service.DATE_FORMAT)
      date_data += get_utc_timedelta()
  tomorrow_data = date_data + datetime.timedelta(days=1)
  return (date_data.strftime(QUERY_DATE_FORMAT),
         tomorrow_data.strftime(QUERY_DATE_FORMAT))


#===============================================================================
# Each of the following _run_* functions execute a particular task.
#  
# Keyword arguments:
#  client: Client to the service being used.
#  options: Contains all attributes required to perform the task
#  args: Additional arguments passed in on the command line, may or may not be
#        required
#===============================================================================
def _run_list(client, options, args):
  cal_user_list = client.get_calendar_user_list(options.cal)
  if not cal_user_list:
    print 'No calendar matches "' + options.cal + '"'
    return
  dates = get_start_and_end(options.date)
  for cal in cal_user_list:
    print ''
    print '[' + str(cal) + ']'
    entries = client.get_events(cal.user,
                                start_date=dates[2],
                                end_date=dates[3],
                                title=options.title,
                                query=options.query)

    if args:
      style_list = args[0].split(',')
    else:
      style_list = googlecl.get_config_option(SECTION_HEADER,
                                              'list_style').split(',')
    for entry in entries:
      print googlecl.service.entry_to_string(entry, style_list,
                                             delimiter=options.delimiter)


def _run_list_today(client, options, args):
  cal_user_list = client.get_calendar_user_list(options.cal)
  if not cal_user_list:
    print 'No calendar matches "' + options.cal + '"'
    return
  start_date, end_date = _tomorrowize()
  for cal in cal_user_list:
    print ''
    print '[' + str(cal) + ']'
    entries = client.get_events(cal.user,
                                start_date=start_date,
                                end_date=end_date,
                                title=options.title,
                                query=options.query)

    if args:
      style_list = args[0].split(',')
    else:
      style_list = googlecl.get_config_option(SECTION_HEADER,
                                              'list_style').split(',')
    for entry in entries:
      print googlecl.service.entry_to_string(entry, style_list,
                                             delimiter=options.delimiter)


def _run_add(client, options, args):
  cal_user_list = client.get_calendar_user_list(options.cal)
  if not cal_user_list:
    print 'No calendar matches "' + options.cal + '"'
    return
  for cal in cal_user_list:
    client.quick_add_event(args, cal.user)


def _run_delete(client, options, args):
  cal_user_list = client.get_calendar_user_list(options.cal)
  if not cal_user_list:
    print 'No calendar matches "' + options.cal + '"'
    return
  dates = get_start_and_end(options.date)
  for cal in cal_user_list:
    print 'For calendar ' + str(cal)
    events = client.get_events(cal.user,
                               start_date=dates[2],
                               end_date=dates[3],
                               title=options.title,
                               query=options.query,
                               expand_recurrence=False)
    try:
      client.delete_events(events, options.date, cal.user)
    except EventsNotFound:
      print 'No events found that match your options!'


TASKS = {'list': googlecl.service.Task('List events on a calendar',
                                       callback=_run_list,
                                       required=['delimiter'],
                                       optional=['title', 'query',
                                                 'date', 'cal']),
         'today': googlecl.service.Task('List events for the next 24 hours',
                                        callback=_run_list_today,
                                        required='delimiter',
                                        optional=['title', 'query', 'cal']),
         'add': googlecl.service.Task('Add event to a calendar',
                                      callback=_run_add,
                                      optional='cal',
                                      args_desc='QUICK_ADD_TEXT'),
         'delete': googlecl.service.Task('Delete event from a calendar',
                                         callback=_run_delete,
                                         required=[['title', 'query']],
                                         optional=['date', 'cal'])}