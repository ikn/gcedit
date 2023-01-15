project_name := gcedit
prefix := /usr/local
datarootdir := $(prefix)/share
exec_prefix := $(prefix)
bindir := $(exec_prefix)/bin
docdir := $(datarootdir)/doc/$(project_name)

ICONS := $(wildcard icons/hicolor/*/apps/*.png)
ICON_PATTERN := icons/hicolor/%/apps/%.png
ICON_PATH = $(patsubst install-%.png,$(ICON_PATTERN),$@)
ICON_PATH_UNINSTALL = $(patsubst uninstall-%.png,$(ICON_PATTERN),$@)

INSTALL_PROGRAM := install
INSTALL_DATA := install -m 644

.PHONY: all clean install uninstall

all:
	./i18n/gen_mo
	python3 setup.py bdist

clean:
	find "$(project_name)" -type d -name '__pycache__' | xargs $(RM) -r
	$(RM) -r build/ dist/ "$(project_name).egg-info/"
	$(RM) -r "$(project_name)/locale/"

install-%.png:
	mkdir -p $(shell dirname $(DESTDIR)$(datarootdir)/$(ICON_PATH))
	$(INSTALL_DATA) $(ICON_PATH) $(DESTDIR)$(datarootdir)/$(ICON_PATH)

uninstall-%.png:
	$(RM) $(DESTDIR)$(datarootdir)/$(ICON_PATH_UNINSTALL)

install: $(patsubst $(ICON_PATTERN),install-%.png,$(ICONS))
	@ # executable
	mkdir -p "$(DESTDIR)$(bindir)/"
	$(INSTALL_PROGRAM) "run_$(project_name)" "$(DESTDIR)$(bindir)/$(project_name)"
	@ # package
	python3 setup.py install --root="$(or $(DESTDIR),/)" --prefix="$(prefix)"
	@ # readme
	mkdir -p "$(DESTDIR)$(docdir)/"
	$(INSTALL_DATA) README.md "$(DESTDIR)$(docdir)/"
	@ # desktop file
	mkdir -p "$(DESTDIR)$(datarootdir)/applications"
	$(INSTALL_DATA) "$(project_name).desktop" "$(DESTDIR)$(datarootdir)/applications"

uninstall: $(patsubst $(ICON_PATTERN),uninstall-%.png,$(ICONS))
	@ # executable
	$(RM) "$(DESTDIR)$(bindir)/$(project_name)"
	@ # package
	./uninstall "$(DESTDIR)" "$(prefix)"
	@ # readme
	$(RM) -r "$(DESTDIR)$(docdir)/"
	@ # desktop file
	$(RM) "$(DESTDIR)$(datarootdir)/applications/$(project_name).desktop"
