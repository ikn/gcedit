# FIXME: $(INSTALL) doesn't work (apparently blank)
INSTALL_PROGRAM := install
INSTALL_DATA := install -m 644

prefix = /usr/local
datarootdir = $(prefix)/share
exec_prefix = $(prefix)
bindir = $(exec_prefix)/bin
docdir = $(datarootdir)/doc/gcedit

.PHONY: all clean distclean install uninstall

all:
	./setup build

clean:
	- $(RM) -r build

distclean: clean
	@ ./unconfigure

install:
	@ # executable
	./set_prefix "$(prefix)"
	mkdir -p "$(DESTDIR)$(bindir)/"
	$(INSTALL_PROGRAM) .run_gcedit.tmp "$(DESTDIR)$(bindir)/gcedit"
	rm .run_gcedit.tmp
	@ # package
	./setup install --prefix="$(DESTDIR)$(prefix)"
	@ # readme
	mkdir -p "$(DESTDIR)$(docdir)/"
	$(INSTALL_DATA) README "$(DESTDIR)$(docdir)/"

uninstall:
	@ # executable
	- $(RM) "$(DESTDIR)$(bindir)/gcedit"
	@ # package
	@ #./setup remove --prefix="$(DESTDIR)$(prefix)"
	- $(RM) -r $(shell ./get_python_lib $(DESTDIR)$(prefix))/{gcedit,gcedit-*.egg-info}
	@ # readme
	- $(RM) -r "$(DESTDIR)$(docdir)/"