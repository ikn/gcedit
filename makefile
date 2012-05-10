# FIXME: $(INSTALL) doesn't work (apparently blank)
INSTALL_PROGRAM := install
INSTALL_DATA := install -m 644

prefix := /usr/local
datarootdir := $(prefix)/share
exec_prefix := $(prefix)
bindir := $(exec_prefix)/bin
docdir := $(datarootdir)/doc/gcedit
python_lib := $(shell ./get_python_lib $(DESTDIR)$(prefix))

ICONS := $(wildcard icons/hicolor/*/apps/gcedit.png)
ICON_PATTERN := icons/hicolor/%/apps/gcedit.png
ICON_PATH = $(patsubst install-%.png,$(ICON_PATTERN),$@)
ICON_PATH_UNINSTALL = $(patsubst uninstall-%.png,$(ICON_PATTERN),$@)

.PHONY: all clean distclean install uninstall

all:
	./setup build

clean:
	- $(RM) -r build

distclean: clean
	@ ./unconfigure

install-%.png:
	mkdir -p $(shell dirname $(DESTDIR)$(datarootdir)/$(ICON_PATH))
	$(INSTALL_DATA) $(ICON_PATH) $(DESTDIR)$(datarootdir)/$(ICON_PATH)

uninstall-%.png:
	$(RM) $(DESTDIR)$(datarootdir)/$(ICON_PATH_UNINSTALL)

aoeu: $(patsubst $(ICON_PATTERN),uninstall-%.png,$(ICONS))

install: $(patsubst $(ICON_PATTERN),install-%.png,$(ICONS))
	@ # executable
	./set_prefix "$(prefix)"
	mkdir -p "$(DESTDIR)$(bindir)/"
	$(INSTALL_PROGRAM) .run_gcedit.tmp "$(DESTDIR)$(bindir)/gcedit"
	$(RM) .run_gcedit.tmp
	@ # package
	./setup install --prefix="$(DESTDIR)$(prefix)"
	@ # readme
	mkdir -p "$(DESTDIR)$(docdir)/"
	$(INSTALL_DATA) README "$(DESTDIR)$(docdir)/"
	@ # desktop file
	mkdir -p "$(DESTDIR)$(datarootdir)/applications"
	$(INSTALL_DATA) gcedit.desktop "$(DESTDIR)$(datarootdir)/applications"

uninstall: $(patsubst $(ICON_PATTERN),uninstall-%.png,$(ICONS))
	@ # executable
	- $(RM) "$(DESTDIR)$(bindir)/gcedit"
	@ # package
	- ./setup remove --prefix="$(DESTDIR)$(prefix)" &> /dev/null || \
	$(RM) -r $(python_lib)/{gcedit,gcedit-*.egg-info}
	@ # readme
	- $(RM) -r "$(DESTDIR)$(docdir)/"
	@ # desktop file
	- $(RM) "$(DESTDIR)$(datarootdir)/applications/gcedit.desktop"