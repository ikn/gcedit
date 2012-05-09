"""gcedit GUI utilities module.

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

    FUNCTIONS

printable_path
printable_filesize
text_viewer
question
error
move_conflict
invalid_name_dialogue
invalid_name

    CLASSES

Progress

"""

from html import escape
from math import log10

from gi.repository import Gtk as gtk, Pango as pango
from .ext.gcutil import valid_name

from . import conf
from .conf import settings

def printable_path (path):
    """Get a printable version of a list-style path."""
    return '/' + '/'.join(path)

def printable_filesize (size):
    """Get a printable version of a filesize in bytes."""
    for factor, suffix in (
        # NOTE: unit for bytes
        (0, _('B')),
        (1, _('KiB')),
        (2, _('MiB')),
        (3, _('GiB')),
        (4, _('TiB'))
    ):
        if size < 1024 ** (factor + 1):
            break
    if factor == 0:
        # bytes
        return '{} {}'.format(size, suffix)
    else:
        size /= (1024 ** factor)
        # 3 significant figures but always show up to units
        dp = max(2 - int(log10(max(size, 1))), 0)
        return ('{:.' + str(dp) + 'f} {}').format(size, suffix)

def text_viewer (text, wrap_mode = gtk.WrapMode.WORD):
    """Get a read-only Gtk.TextView widget in a Gtk.ScrolledWindow.

text_viewer(text, wrap_mode = Gtk.WrapMode.WORD) -> widget



"""
    w = gtk.ScrolledWindow()
    v = gtk.TextView()
    w.add(v)
    v.set_editable(False)
    v.set_cursor_visible(False)
    v.set_wrap_mode(wrap_mode)
    v.get_buffer().set_text(text)
    v.set_vexpand(True)
    v.set_hexpand(True)
    v.set_valign(gtk.Align.FILL)
    v.set_halign(gtk.Align.FILL)
    v.show()
    return w

def question (title, msg, options, parent = None, default = None,
              warning = False, ask_again = None, return_dialogue = False):
    """Show a dialogue asking a question.

question(title, msg, options[, parent][, default], warning = False[,
         ask_again], return_dialogue = False) -> response

title: dialogue title text.
msg: text to display.
options: a list of options to present as buttons, where each is the button text
         or a stock ID.
parent: dialogue parent.
default: the index of the option in the list that should be selected by default
         (pressing enter normally).
warning: whether this is a warning dialogue (instead of just a question).
ask_again: show a 'Don't ask again' checkbox.  This is
           (setting_key, match_response), where, if the checkbox is ticked and
           the response is match_response, setting_key is added to the
           'disabled_warnings' setting set.  This argument is ignored if
           return_dialogue is True.
return_dialogue: whether to return the created dialogue instead of running it.

response: The index of the clicked button in the list, or a number less than 0
          if the dialogue was closed.

"""
    mt = gtk.MessageType.WARNING if warning else gtk.MessageType.QUESTION
    d = gtk.MessageDialog(parent, gtk.DialogFlags.DESTROY_WITH_PARENT,
                          mt, gtk.ButtonsType.NONE, msg)
    d.add_buttons(*(sum(((o, i) for i, o in enumerate(options)), ())))
    d.set_title(title)
    # FIXME: sets default to 0 if we don't set it here
    if default is not None:
        d.set_default_response(default)
    if return_dialogue:
        return d
    else:
        if ask_again is not None:
            # add checkbox
            c = gtk.CheckButton.new_with_mnemonic(_('_Don\'t ask again'))
            d.get_message_area().pack_start(c, False, False, 0)
            c.show()
        response = d.run()
        if ask_again is not None:
            # handle checkbox value
            setting_key, match_response = ask_again
            if c.get_active() and response == match_response:
                warnings = settings['disabled_warnings']
                warnings.add(setting_key)
                settings['disabled_warnings'] = warnings
        d.destroy()
        return response

def error (msg, parent = None, *widgets):
    """Show an error dialogue.

error(msg, parent = None, *widgets)

msg: text to display.
parent: dialogue parent.
widgets: widgets to add to the same grid as the text, which is at (0, 0) with
         size (1, 1).  A widget can be (widget, x, y, w, h) to determine its
         position; otherwise, it is placed the first free cell in column 0 once
         all widgets with given positions have been placed.
         widget.show() is called.

"""
    # using .run(), so don't need modal flag
    d = gtk.Dialog('Error', parent, gtk.DialogFlags.DESTROY_WITH_PARENT,
                   (gtk.STOCK_OK, gtk.ResponseType.OK))
    # label
    msg = gtk.Label(msg)
    msg.set_line_wrap(True)
    msg.set_selectable(True)
    msg.set_halign(gtk.Align.START)
    msg.set_valign(gtk.Align.START)
    # some properties
    d.set_resizable(False)
    d.set_default_response(gtk.ResponseType.OK)
    d.set_border_width(6)
    # grid
    g = gtk.Grid()
    d.get_content_area().pack_start(g, True, True, 0)
    g.set_border_width(6)
    g.set_property('margin-bottom', 12)
    g.set_column_spacing(12)
    g.set_row_spacing(12)
    # add label and given widgets, if any
    used_rows = set()
    todo = []
    min_x = 0
    min_y = 0
    max_y = 1
    i = 0
    for widget in ((msg, 0, 0, 1, 1),) + widgets:
        if isinstance(widget, gtk.Widget):
            # leave until later
            todo.append(widget)
        else:
            # place where asked
            widget, x, y, w, h = widget
            if x <= 0 and x + w > 0:
                used_rows.update(range(y, y + h))
            g.attach(widget, x, y, w, h)
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_y = max(max_y, y + w)
        widget.show()
    for widget in todo:
        # place in first free cell in column 0
        while i in used_rows:
            i += 1
        g.attach(widget, 0, i, 1, 1)
        max_y = max(max_y, i + 1)
        i += 1
    # add image
    img = gtk.Image.new_from_stock(gtk.STOCK_DIALOG_ERROR, gtk.IconSize.DIALOG)
    img.set_halign(gtk.Align.CENTER)
    img.set_valign(gtk.Align.START)
    g.attach(img, min_x - 1, min_y, 1, max_y - min_y)
    img.show()
    # run
    g.show()
    d.run()
    d.destroy()

def move_conflict (fn_from, f_to, parent = None, invalid = False):
    """Show a dialogue that handles a conflict in moving a file.

move_conflict(fn_from, fn_to[, parent], invalid = False) -> action

fn_from: the filename to move from.
f_to: the full file path to move to (in a printable format).
parent: dialogue parent.
invalid: whether the problem is that the destination is invalid (as opposed to
         the destination existing).

action: True to overwrite (not for an invalid name), False to cancel the move,
        or a string to move to that name instead.

"""
    # get dialogue
    if invalid:
        msg = _('The file \'{}\' cannot be moved to \'{}\' because the ' \
                'destination name is invalid.')
    else:
        msg = _('The file \'{}\' cannot be moved to \'{}\' because the ' \
                'destination file exists.')
    msg = msg.format(fn_from, f_to)
    buttons = ['_Rename', gtk.STOCK_CANCEL]
    if not invalid:
        buttons.append('_Overwrite')
    d = question('Filename Conflict', msg, buttons, parent, 1, warning = True,
                 return_dialogue = True)
    # rename button sensitivity
    d.set_response_sensitive(0, False)
    def set_sensitive (e, *args):
        renaming = e.get_text()
        d.set_response_sensitive(0, renaming)
        d.set_default_response(0 if renaming else 1)
        e.set_activates_default(renaming)
    # make message left-aligned
    msg_area = d.get_message_area()
    msg_area.get_children()[0].set_alignment(0, .5)
    # add error message
    err = gtk.Label('<i>{}</i>'.format(escape(_('Error: invalid filename.'))))
    err.set_use_markup(True)
    err.set_alignment(0, .5)
    msg_area.pack_start(err, False, False, 0)
    # add entry
    h = gtk.Box(False, 6)
    msg_area.pack_start(h, False, False, 0)
    # NOTE: name as in filename
    h.pack_start(gtk.Label(_('New name:')), False, False, 0)
    e = gtk.Entry()
    h.pack_start(e, False, False, 0)
    e.connect('changed', set_sensitive)
    h.show_all()
    if invalid:
        # add invalid name details
        details = _invalid_name_details_expander()
        msg_area.pack_start(details, False, False, 0)
        details.show()
    # run
    while True:
        response = d.run()
        if response == 2:
            action = True
        elif response == 0:
            action = e.get_text()
            if conf.INVALID_FN_CHARS[isinstance(action, str)].intersection(action):
                e.grab_focus()
                err.show()
                continue
        else:
            action = False
        break
    d.destroy() # need to do this after we retrieve entry's text
    return action

def _invalid_name_details_expander ():
    """Get a Gtk.Expander with invalid name details."""
    e = gtk.Expander()
    e.set_label(_('_Details'))
    e.set_use_underline(True)
    l = gtk.Label(_('It must be possible to encode file and directory names ' \
                    'using the shift-JIS encoding, and \'/\' and null bytes ' \
                    '(\'\\0\') are not allowed.'))
    e.add(l)
    l.set_line_wrap(True)
    l.show()
    return e

def invalid_name_dialogue (paths, parent = None):
    """Show an error dialogue for trying to create files with invalid names.

invalid_name_dialogue(paths[, parent])

paths: a list of the invalid paths (in printable form).
parent: dialogue parent.

"""
    widgets = []
    if len(paths) == 1:
        # NOTE: name as in file/directory name
        msg = _('Couldn\'t create \'{}\' because its name is invalid.')
        msg = msg.format(paths)
    else:
        # NOTE: name as in file/directory name
        msg = _('The following items couldn\'t be created because their ' \
                'names are invalid:')
        widgets.append(text_viewer('\n'.join(paths), gtk.WrapMode.NONE))
    # details
    e = _invalid_name_details_expander()
    widgets.append(e)
    error(msg, parent, *widgets)

def invalid_name (name):
    """Check if a filename is valid."""
    if conf.INVALID_FN_CHARS[isinstance(name, str)].intersection(name):
        return False
    else:
        return not valid_name(name)


class Progress (gtk.Dialog):
    """Show a progress dialogue.  Subclass of Gtk.Dialog.

Act directly on the bar attribute to control the progress bar itself.

    CONSTRUCTOR

Progress(title[, cancel][, pause, unpause][, parent], autoclose = False)

title: dialogue title.
cancel: if a cancel button should be shown, a callback for when it is clicked.
pause: if a pause button should be shown, a callback for when it is clicked.
unpause: when the pause button is clicked, it is replaced by a continue button,
         and this is its callback.
parent: parent widget.
autoclose: the initial value of the 'Automatically close when finished'
           checkbox.

    METHODS

set_item
finish

    ATTRIBUTES

bar: Gtk.ProgressBar instance.
item: current item that's being processed, or None.
autoclose: the checkbox.

"""
    def __init__ (self, title, cancel = None, pause = None, unpause = None,
                  parent = None, autoclose = False):
        self.item = None
        # create dialogue
        flags = gtk.DialogFlags.MODAL | gtk.DialogFlags.DESTROY_WITH_PARENT
        buttons = []
        if cancel is not None:
            buttons += [gtk.STOCK_CANCEL, 0]
        if pause is not None:
            buttons += [_('_Pause'), 1]
        gtk.Dialog.__init__(self, title, parent, flags, buttons)
        if pause is not None:
            self.set_default_response(1)
        # callbacks
        for b in self.get_action_area().get_children():
            if b.get_label() == gtk.STOCK_CANCEL:
                b.connect('clicked', cancel)
            else: # b.get_label() == _('_Pause')
                self._pause = pause
                self._unpause = unpause
                b.connect('clicked', self._toggle_paused)
                self._pause_icon = gtk.Image.new_from_stock(
                    gtk.STOCK_MEDIA_PAUSE, gtk.IconSize.BUTTON)
                self._unpause_icon = gtk.Image.new_from_stock(
                    gtk.STOCK_MEDIA_PLAY, gtk.IconSize.BUTTON)
                b.set_image(self._pause_icon)
        # some properties
        self.set_border_width(12)
        self.set_default_size(400, 0)
        self.set_deletable(False)
        self._nodel_id = self.connect('delete-event', lambda *args: True)
        # add widgets
        v = self.vbox
        v.set_spacing(6)
        # heading
        head = escape(title)
        head = '<span weight="bold" size="larger">{}\n</span>'.format(head)
        head = gtk.Label(head)
        head.set_use_markup(True)
        head.set_alignment(0, .5)
        v.pack_start(head, False, False, 0)
        # bar
        self.bar = gtk.ProgressBar()
        v.pack_start(self.bar, False, False, 0)
        self.bar.set_show_text(True)
        # current item
        self._item = i = gtk.Label()
        i.set_alignment(0, .5)
        i.set_ellipsize(pango.EllipsizeMode.END) # to avoid dialogue resizing
        i.show()
        # checkbox
        text = _('_Automatically close when finished')
        self.autoclose = c = gtk.CheckButton.new_with_mnemonic(text)
        v.pack_end(c, False, False, 0)
        c.set_active(autoclose)
        v.show_all()

    def _toggle_paused (self, b):
        if b.get_label() == _('_Pause'):
            # currently not paused
            b.set_label(_('_Continue'))
            b.set_image(self._unpause_icon)
            self._pause(b)
        else:
            # already paused
            b.set_label(_('_Pause'))
            b.set_image(self._pause_icon)
            self._unpause(b)

    def set_item (self, item = None):
        """Set the text that displays the current item being progressed.

If no argument is given, the current item text is removed from the dialogue.

"""
        if item is None:
            if self.item is not None:
                self.vbox.remove(self._item)
        else:
            self._item.set_text('<i>{}</i>'.format(escape(item)))
            # for some reason we have to do this every time we set the text
            self._item.set_use_markup(True)
            if self.item is None:
                self.vbox.pack_start(self._item, False, False, 0)
        self.item = item

    def finish (self):
        """Allow the dialogue to be closed.

Returns whether the autoclose checkbox is active.

If the return value is False, you should call Progress.run.  If the checkbox is
then ticked, the response returned from this call will be 0.

"""
        # remove old buttons
        a = self.get_action_area()
        for b in a.get_children():
            a.remove(b)
        # add close button
        self.add_buttons(gtk.STOCK_CLOSE, gtk.ResponseType.CLOSE)
        self.set_default_response(gtk.ResponseType.CLOSE)
        self.set_deletable(True)
        self.disconnect(self._nodel_id)
        # handle autoclose
        autoclose = self.autoclose.get_active()
        if not autoclose:
            f = lambda *args: self.response(0)
            self.autoclose.connect('toggled', f)
        return autoclose