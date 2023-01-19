project_name := gcedit
prefix := /usr/local
datarootdir := $(prefix)/share
exec_prefix := $(prefix)
bindir := $(exec_prefix)/bin
docdir := $(datarootdir)/doc/$(project_name)

ICON_ROOT := icons/hicolor
ICON_DIRS := $(patsubst $(ICON_ROOT)/%/apps,%,$(wildcard $(ICON_ROOT)/*/apps))
ICON_DIR_PATH = $(ICON_ROOT)/$(patsubst icons-install-%,%,$@)/apps
ICON_DIR_PATH_UNINSTALL = $(ICON_ROOT)/$(patsubst icons-uninstall-%,%,$@)/apps
ICON_PATH_UNINSTALL = $(wildcard $(ICON_DIR_PATH_UNINSTALL)/*)

INSTALL_PROGRAM := install
INSTALL_DATA := install -m 644

.PHONY: all clean distclean install uninstall

all:
	./i18n/gen_mo
	python3 setup.py bdist

clean:
	$(RM) -r build/ dist/ "$(project_name).egg-info/"
	$(RM) -r "$(project_name)/locale/"

distclean: clean
	find "$(project_name)" -type d -name '__pycache__' | xargs $(RM) -r

icons-install-%:
	mkdir -p "$(DESTDIR)$(datarootdir)/$(ICON_DIR_PATH)"
	$(INSTALL_DATA) -t "$(DESTDIR)$(datarootdir)/$(ICON_DIR_PATH)" \
	    $(wildcard $(ICON_DIR_PATH)/*)

icons-uninstall-%:
	$(RM) $(patsubst $(ICON_DIR_PATH_UNINSTALL)/%,$(DESTDIR)$(datarootdir)/$(ICON_DIR_PATH_UNINSTALL)/%,$(ICON_PATH_UNINSTALL))

install: $(patsubst %,icons-install-%,$(ICON_DIRS))
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

uninstall: $(patsubst %,icons-uninstall-%,$(ICON_DIRS))
	@ # executable
	$(RM) "$(DESTDIR)$(bindir)/$(project_name)"
	@ # package
	./uninstall "$(DESTDIR)" "$(prefix)"
	@ # readme
	$(RM) -r "$(DESTDIR)$(docdir)/"
	@ # desktop file
	$(RM) "$(DESTDIR)$(datarootdir)/applications/$(project_name).desktop"
