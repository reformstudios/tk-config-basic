# Copyright (c) 2017 Shotgun Software Inc.
# 
# CONFIDENTIAL AND PROPRIETARY
# 
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit 
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your 
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights 
# not expressly granted therein are reserved by Shotgun Software Inc.

import os
import pprint
import maya.cmds as cmds
import maya.mel as mel
import sgtk

HookBaseClass = sgtk.get_hook_baseclass()


class MayaSessionPublishPlugin(HookBaseClass):
    """
    Plugin for publishing an open maya session.
    """

    @property
    def icon(self):
        """
        Path to an png icon on disk
        """

        # look for icon one level up from this hook's folder in "icons" folder
        return os.path.join(
            self.disk_location,
            os.pardir,
            "icons",
            "publish.png"
        )

    @property
    def name(self):
        """
        One line display name describing the plugin
        """
        return "Publish Maya work file"

    @property
    def description(self):
        """
        Verbose, multi-line description of what the plugin does. This can
        contain simple html for formatting.
        """
        return """
        This plugin will save and publish the current Maya session. If the
        session has not been saved before or the path can not be determined,
        validation will fail. If a version number is detected in the file name,
        the session will be saved to the next version once publishing is
        complete.
        """

    @property
    def settings(self):
        """
        Dictionary defining the settings that this plugin expects to receive
        through the settings parameter in the accept, validate, publish and
        finalize methods.

        A dictionary on the following form::

            {
                "Settings Name": {
                    "type": "settings_type",
                    "default": "default_value",
                    "description": "One line description of the setting"
            }

        The type string should be one of the data types that toolkit accepts as
        part of its environment configuration.
        """
        return {
            "Publish Type": {
                "type": "shotgun_publish_type",
                "default": "Maya Scene",
                "description": "SG publish type to associate publishes with."
            },
        }

    @property
    def item_filters(self):
        """
        List of item types that this plugin is interested in.

        Only items matching entries in this list will be presented to the
        accept() method. Strings can contain glob patters such as *, for example
        ["maya.*", "file.maya"]
        """
        return ["maya.session"]

    def accept(self, settings, item):
        """
        Method called by the publisher to determine if an item is of any
        interest to this plugin. Only items matching the filters defined via the
        item_filters property will be presented to this method.

        A publish task will be generated for each item accepted here. Returns a
        dictionary with the following booleans:

            - accepted: Indicates if the plugin is interested in this value at
                all. Required.
            - enabled: If True, the plugin will be enabled in the UI, otherwise
                it will be disabled. Optional, True by default.
            - visible: If True, the plugin will be visible in the UI, otherwise
                it will be hidden. Optional, True by default.
            - checked: If True, the plugin will be checked in the UI, otherwise
                it will be unchecked. Optional, True by default.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process

        :returns: dictionary with boolean keys accepted, required and enabled
        """

        path = _session_path()

        if not path:
            # the session has not been saved before (no path determined).
            # provide a save button. the session will need to be saved before
            # validation will succeed.
            self.logger.warn(
                "The Maya session has not been saved.",
                extra=_get_save_as_action()
            )

        self.logger.info(
            "Maya '%s' plugin accepted the current Maya session." %
            (self.name,)
        )
        return {
            "accepted": True,
            "checked": True
        }

    def validate(self, settings, item):
        """
        Validates the given item to check that it is ok to publish. Returns a
        boolean to indicate validity.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        :returns: True if item is valid, False otherwise.
        """

        publisher = self.parent
        path = _session_path()

        if not path:
            # the session still requires saving. provide a save button.
            # validation fails.
            self.logger.error(
                "The Maya session has not been saved.",
                extra=_get_save_as_action()
            )
            return False

        # ensure we have an updated project root
        project_root = cmds.workspace(q=True, rootDirectory=True)
        item.properties["project_root"] = project_root

        # warn if no project root could be determined.
        if not project_root:
            self.logger.warning(
                "Your session is not part of a maya project.",
                extra={
                    "action_button": {
                        "label": "Set Project",
                        "tooltip": "Set the maya project",
                        "callback": lambda: mel.eval('setProject ""')
                    }
                }
            )

        # get the path in a normalized state. no trailing separator,
        # separators are appropriate for current os, no double separators,
        # etc.
        sgtk.util.ShotgunPath.normalize(path)

        # get the publish name for this file path. this will ensure we get a
        # consistent publish name when looking up existing publishes.
        publish_name = publisher.util.get_publish_name(path)

        self.logger.info("Publish name will be: %s" % (publish_name,))

        # see if there are any other publishes of this path with a status.
        # Note the name, context, and path *must* match the values supplied to
        # register_publish in the publish phase in order for this to return an
        # accurate list of previous publishes of this file.
        publishes = publisher.util.get_conflicting_publishes(
            item.context,
            path,
            publish_name,
            filters=["sg_status_list", "is_not", None]
        )

        if publishes:
            conflict_info = (
                "If you continue, these conflicting publishes will no longer "
                "be available to other users via the loader:<br>"
                "<pre>%s</pre>" % (pprint.pformat(publishes),)
            )
            self.logger.warn(
                "Found %s conflicting publishes in Shotgun" %
                (len(publishes),),
                extra={
                    "action_show_more_info": {
                        "label": "Show Conflicts",
                        "tooltip": "Show the conflicting publishes in Shotgun",
                        "text": conflict_info
                    }
                }
            )

        # if the file has a version number in it, see if the next version exists
        next_version_path = publisher.util.get_next_version_path(path)
        if next_version_path and os.path.exists(next_version_path):

            # determine the next available version_number. just keep asking for
            # the next one until we get one that doesn't exist.
            while os.path.exists(next_version_path):
                next_version_path = publisher.util.get_next_version_path(
                    next_version_path)

            # now extract the version number of the next available to display
            # to the user
            version = publisher.util.get_version_number(next_version_path)

            self.logger.error(
                "The next version of this file already exists on disk.",
                extra={
                    "action_button": {
                        "label": "Save to v%s" % (version,),
                        "tooltip": "Save to the next available version number, "
                                   "v%s" % (version,),
                        "callback": lambda: _save_session(next_version_path)
                    }
                }
            )
            return False

        return True

    def publish(self, settings, item):
        """
        Executes the publish logic for the given item and settings.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent

        # get the path in a normalized state. no trailing separator, separators
        # are appropriate for current os, no double separators, etc.
        path = sgtk.util.ShotgunPath.normalize(_session_path())

        # ensure the session is saved
        _save_session(path)

        # get the publish name for this file path. this will ensure we get a
        # consistent name across version publishes of this file.
        publish_name = publisher.util.get_publish_name(path)

        # extract the version number for publishing. use 1 if no version in path
        version_number = publisher.util.get_version_number(path) or 1

        # arguments for publish registration
        self.logger.info("Registering publish...")
        publish_data = {
            "tk": publisher.sgtk,
            "context": item.context,
            "comment": item.description,
            "path": path,
            "name": publish_name,
            "version_number": version_number,
            "thumbnail_path": item.get_thumbnail_as_path(),
            "published_file_type": settings["Publish Type"].value,
            "dependency_paths": _maya_find_additional_session_dependencies(),
        }

        # log the publish data for debugging
        self.logger.debug(
            "Populated Publish data...",
            extra={
                "action_show_more_info": {
                    "label": "Publish Data",
                    "tooltip": "Show the complete Publish data dictionary",
                    "text": "<pre>%s</pre>" % (pprint.pformat(publish_data),)
                }
            }
        )

        # create the publish and stash it in the item properties for other
        # plugins to use.
        item.properties["sg_publish_data"] = sgtk.util.register_publish(
            **publish_data)

        # inject the publish path such that children can refer to it when
        # updating dependency information
        item.properties["sg_publish_path"] = path

        self.logger.info("Publish registered!")

        # now that we've published. keep a handle on the path that was published
        item.properties["path"] = path

    def finalize(self, settings, item):
        """
        Execute the finalization pass. This pass executes once all the publish
        tasks have completed, and can for example be used to version up files.

        :param settings: Dictionary of Settings. The keys are strings, matching
            the keys returned in the settings property. The values are `Setting`
            instances.
        :param item: Item to process
        """

        publisher = self.parent

        # get the data for the publish that was just created in SG
        publish_data = item.properties["sg_publish_data"]

        # ensure conflicting publishes have their status cleared
        publisher.util.clear_status_for_conflicting_publishes(
            item.context, publish_data)

        self.logger.info(
            "Cleared the status of all previous, conflicting publishes")

        path = item.properties["path"]
        self.logger.info(
            "Publish created for file: %s" % (path,),
            extra={
                "action_show_in_shotgun": {
                    "label": "Show Publish",
                    "tooltip": "Open the Publish in Shotgun.",
                    "entity": publish_data
                }
            }
        )

        # insert the path into the properties
        item.properties["next_version_path"] = self._bump_file_version(path)

    def _bump_file_version(self, path):
        """
        Save the supplied path to the next version on disk.
        """

        publisher = self.parent
        version_number = publisher.util.get_version_number(path)

        if version_number is None:
            self.logger.debug(
                "No version number detected in the publish path. "
                "Skipping the bump file version step."
            )
            return None

        self.logger.info("Incrementing session file version number...")

        next_version_path = publisher.util.get_next_version_path(path)

        # nothing to do if the next version path can't be determined or if it
        # already exists.
        if not next_version_path:
            self.logger.warning("Could not determine the next version path.")
            return None
        elif os.path.exists(next_version_path):
            self.logger.warning(
                "The next version of the path already exists",
                extra={
                    "action_show_folder": {
                        "path": next_version_path
                    }
                }
            )
            return None

        # save the session to the new path
        _save_session(next_version_path)
        self.logger.info("Session saved as: %s" % (next_version_path,))

        return next_version_path


def _maya_find_additional_session_dependencies():
    """
    Find additional dependencies from the session
    """
    # default implementation looks for references and
    # textures (file nodes)
    ref_paths = set()

    # first let's look at maya references
    ref_nodes = cmds.ls(references=True)
    for ref_node in ref_nodes:
        # get the path:
        ref_path = cmds.referenceQuery(ref_node, filename=True)
        # make it platform dependent
        # (maya uses C:/style/paths)
        ref_path = ref_path.replace("/", os.path.sep)
        if ref_path:
            ref_paths.add(ref_path)

    # now look at file texture nodes
    for file_node in cmds.ls(l=True, type="file"):
        # ensure this is actually part of this session and not referenced
        if cmds.referenceQuery(file_node, isNodeReferenced=True):
            # this is embedded in another reference, so don't include it in
            # the breakdown
            continue

        # get path and make it platform dependent
        # (maya uses C:/style/paths)
        texture_path = cmds.getAttr(
            "%s.fileTextureName" % file_node).replace("/", os.path.sep)
        if texture_path:
            ref_paths.add(texture_path)

    return list(ref_paths)


def _session_path():
    """
    Return the path to the current session
    :return:
    """
    return cmds.file(query=True, sn=True)


def _save_session(path):
    """
    Save the current session to the supplied path.
    """

    # Maya can choose the wrong file type so we should set it here
    # explicitly based on the extension
    maya_file_type = None
    if path.lower().endswith(".ma"):
        maya_file_type = "mayaAscii"
    elif path.lower().endswith(".mb"):
        maya_file_type = "mayaBinary"

    cmds.file(rename=path)

    # save the scene:
    if maya_file_type:
        cmds.file(save=True, force=True, type=maya_file_type)
    else:
        cmds.file(save=True, force=True)


def _get_save_as_action():
    """

    Simple helper for returning a log action dict for saving the session
    """
    return {
        "action_button": {
            "label": "Save As...",
            "tooltip": "Save the current session",
            "callback": cmds.SaveScene
        }
    }