import os
import logging

from avocado.utils import process
from virttest import virsh
from virttest import xml_utils
from virttest import libvirt_storage
from virttest import libvirt_xml
from virttest.utils_test import libvirt as utlv
from virttest.libvirt_xml import pool_xml

from provider import libvirt_version


def run(test, params, env):
    """
    Test command: virsh pool-create.

    Create a libvirt pool from an XML file. The file could be given by tester or
    generated by dumpxml a pre-defined pool.
    """
    pool_xml_f = params.get("pool_create_xml_file", "/PATH/TO/POOL.XML")
    pool_name = params.get("pool_create_name", "virt_test_pool_tmp")
    option = params.get("pool_create_extra_option", "")
    readonly_mode = "yes" == params.get("pool_create_readonly_mode", "no")
    status_error = "yes" == params.get("status_error", "no")
    pre_def_pool = "yes" == params.get("pre_def_pool", "no")
    pool_type = params.get("pool_type", "dir")
    source_format = params.get("pool_src_format", "")
    source_name = params.get("pool_source_name", "")
    source_path = params.get("pool_source_path", "/")
    pool_target = params.get("pool_target", "pool_target")
    duplicate_element = params.get("pool_create_duplicate_element", "")
    new_pool_name = params.get("new_pool_create_name")
    no_disk_label = "yes" == params.get("no_disk_label", "no")

    if not libvirt_version.version_compare(1, 0, 0):
        if pool_type == "gluster":
            test.cancel("Gluster pool is not supported in current"
                        " libvirt version.")

    if "/PATH/TO/POOL.XML" in pool_xml_f:
        test.cancel("Please replace %s with valid pool xml file" %
                    pool_xml_f)
    pool_ins = libvirt_storage.StoragePool()
    if pre_def_pool and pool_ins.pool_exists(pool_name):
        test.fail("Pool %s already exist" % pool_name)

    kwargs = {'image_size': '1G', 'source_path': source_path,
              'source_name': source_name, 'source_format': source_format,
              'emulated_image': "emulated-image", 'pool_target': pool_target,
              'pool_name': pool_name}
    params.update(kwargs)
    pvt = utlv.PoolVolumeTest(test, params)
    old_uuid = None
    new_device_name = None
    if pre_def_pool:
        try:
            pvt.pre_pool(**params)
            virsh.pool_dumpxml(pool_name, to_file=pool_xml_f)
            old_uuid = virsh.pool_uuid(pool_name).stdout.strip()
            if no_disk_label:
                # Update <device_path>
                logging.debug("Try to update device path")
                new_device_name = utlv.setup_or_cleanup_iscsi(True)
                p_xml = pool_xml.PoolXML.new_from_dumpxml(pool_name)
                s_xml = pool_xml.SourceXML()
                s_xml.device_path = new_device_name
                p_xml.set_source(s_xml)
                pool_xml_f = p_xml.xml
            if duplicate_element == "name":
                pass
            elif duplicate_element == "uuid":
                pass
            elif duplicate_element == "source":
                # Remove <uuid> and update <name>
                cmd = "sed -i '/<uuid>/d' %s" % pool_xml_f
                process.run(cmd, shell=True)
                cmd = "sed -i 's/<name>.*<\/name>/<name>%s<\/name>/g' %s" % (new_pool_name, pool_xml_f)
                process.run(cmd, shell=True)
            else:
                # The transient pool will gone after destroyed
                virsh.pool_destroy(pool_name)
            new_source_format = params.get("new_pool_src_format")
            if new_source_format:
                cmd = "sed -i s/type=\\\'%s\\\'/type=\\\'%s\\\'/g %s" % (
                    source_format, new_source_format, pool_xml_f)
                process.run(cmd, shell=True)
            # Remove uuid
            cmd = "sed -i '/<uuid>/d' %s" % pool_xml_f
            process.run(cmd, shell=True)
        except Exception as details:
            pvt.cleanup_pool(**params)
            if new_device_name:
                utlv.setup_or_cleanup_iscsi(False)
            test.error("Error occurred when prepare pool xml:\n %s"
                       % details)
    # Create an invalid pool xml file
    if pool_xml_f == "invalid-pool-xml":
        tmp_xml_f = xml_utils.TempXMLFile()
        tmp_xml_f.write('"<pool><<<BAD>>><\'XML</name\>'
                        '!@#$%^&*)>(}>}{CORRUPTE|>!</pool>')
        tmp_xml_f.flush()
        pool_xml_f = tmp_xml_f.name
    # Readonly mode
    ro_flag = False
    if readonly_mode:
        logging.debug("Readonly mode test")
        ro_flag = True
    # Run virsh test
    if os.path.exists(pool_xml_f):
        with open(pool_xml_f, 'r') as f:
            logging.debug("Create pool from file:\n %s", f.read())
    try:
        cmd_result = virsh.pool_create(pool_xml_f, option, ignore_status=True,
                                       debug=True, readonly=ro_flag)
        err = cmd_result.stderr.strip()
        status = cmd_result.exit_status
        if not status_error:
            if status:
                test.fail(err)
            utlv.check_actived_pool(pool_name)
            pool_detail = libvirt_xml.PoolXML.get_pool_details(pool_name)
            logging.debug("Pool detail: %s", pool_detail)
            if pool_detail['uuid'] == old_uuid:
                test.fail("New created pool still use the old UUID %s"
                          % old_uuid)
        else:
            if status == 0:
                test.fail("Expect fail, but run successfully.")
            else:
                logging.debug("Command fail as expected")
    finally:
        pvt.cleanup_pool(**params)
        if new_device_name:
            utlv.setup_or_cleanup_iscsi(False)
        if os.path.exists(pool_xml_f):
            os.remove(pool_xml_f)
