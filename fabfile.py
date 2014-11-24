from fabric.contrib.files import exists
from fabric.api import run, env, sudo, local, cd
from fabric.api import hide, parallel
import os
from pipes import quote

from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
import libcloud.security


def _get_env_value(env_name, default_value):
    env_value = os.environ.get(env_name)
    if env_value is None:
        return default_value
    else:
        return env_value


def _get_env_array(env_name, default_value, delimiter):
    env_value = os.environ.get(env_name)
    if env_value is None:
        return default_value
    else:
        return env_value.split(delimiter)

env.forward_agent = True
env.use_ssh_config = True

os_user = os.environ["OS_USERNAME"]
os_tenant_name = os.environ["OS_TENANT_NAME"]
os_password = os.environ["OS_PASSWORD"]
os_url = os.environ["OS_AUTH_URL"]+"/tokens"

cluster_num_of_nodes = int(os.environ["LEADS_CLUSTER_NUM_OF_NODES"])
cluster_name = _get_env_value("LEADS_CLUSTER_NAME", "leads_m24_cluster")

cluster_security_group_name = cluster_name + "_internal"
cluster_port_communication = ['54200', '55200', '22']

cluster_external_access_sg_name = cluster_name + "_external_access"
cluster_external_access_ports = ['22']

# the openstack primary
cluster_primary_ssh_key = _get_env_value("LEADS_CLUSTER_PRIMARY_SSH_KEY", "wb-new-key")
# injected using cloud-init
# on C&H, the ssh key must be imported to the installation
# otherwise you can
cluster_additinal_ssh_keys = _get_env_array("LEADS_CLUSTER_ADD_SSH_KEYS", [], ',')

node_name_prefix = cluster_name + "_node"
node_flavor = "cloudcompute.s"
image_name = "Ubuntu 14.04 LTS x64"
node_metadata = {"leads_cluster_name":  cluster_name}

infinispan_package_url = 'https://object-hamm5.cloudandheat.com:8080/'\
                         'v1/AUTH_73e8d4d1688f4e1f86926d4cb897091f/infinispan/infinispan-server-7.0.1-SNAPSHOT.tgz?'\
                         'temp_url_sig=76fcfe3e623edea4642e443ba5ff04e076395b85&'\
                         'temp_url_expires=1419376046'

hadoop_package_url = 'https://archive.apache.org/dist/hadoop/core/hadoop-2.5.2/hadoop-2.5.2.tar.gz'

Driver = get_driver(Provider.OPENSTACK)
os_conn = Driver(os_user, os_password,
                 ex_tenant_name=os_tenant_name,
                 ex_force_auth_url=os_url,
                 ex_force_auth_version='2.0_password')

libcloud.security.VERIFY_SSL_CERT = False


def create_cluster():
    external_sec_group = _create_external_access_sg(cluster_external_access_sg_name)
    internal_sec_group = _create_cluster_internal_sg(cluster_security_group_name)

    sec_groups = [external_sec_group, internal_sec_group]
    # create a VM
    nodes = []
    for i in range(0, cluster_num_of_nodes):
        n = _create_instance(cluster_name, node_name_prefix + "_" + str(i), sec_groups)
        nodes.append(n)

    n_and_ips = os_conn.wait_until_running(nodes)
    _generate_ssh_config(n_and_ips)
    _generate_host_file(n_and_ips)
    _generate_private_ips_file(n_and_ips)


def _create_external_access_sg(sec_group_name):
    sg = _find_sg_by_name(sec_group_name)
    if not sg:
        sec_group = os_conn.ex_create_security_group(
            name=sec_group_name,
            description="External access to leads project demo cluster"
            )
        _create_external_sg_rules(sec_group, cluster_external_access_ports)
    else:
        assert len(sg) == 1
        sec_group = sg[0]
    return sec_group


def _find_sg_by_name(sec_group_name):
    all_sec_groups = os_conn.ex_list_security_groups()
    return [s for s in all_sec_groups if s.name == sec_group_name]


def _create_external_sg_rules(sec_group, ports):
    for port in ports:
        os_conn.ex_create_security_group_rule(
            sec_group,
            ip_protocol='tcp',
            from_port=port,
            to_port=port,
            cidr='0.0.0.0/0'
            )


def _create_cluster_internal_sg(sec_group_name):
    sg = _find_sg_by_name(sec_group_name)
    if not sg:
        sec_group = os_conn.ex_create_security_group(
            name=sec_group_name,
            description="Internal for leads project demo cluster")
        _create_security_group_rules(sec_group, cluster_port_communication)
    else:
        assert len(sg) == 1
        sec_group = sg[0]
    return sec_group


def _create_security_group_rules(sec_group, ports):
    for port in ports:
        os_conn.ex_create_security_group_rule(
            sec_group,
            ip_protocol='tcp',
            from_port=port,
            to_port=port,
            source_security_group=sec_group
            )


def _create_instance(cluster_name, node_name, sec_groups):
    """
    """
    existing_node = _find_node_by_name(cluster_name, node_name)

    if not existing_node:
        img = _get_image(image_name)
        size = _get_flavor(node_flavor)

        primary_ssh_key = _get_primary_ssh_key(cluster_primary_ssh_key)
        args = {'name': node_name, 'image': img, 'size': size,
                'ex_keyname': primary_ssh_key.name, 'ex_security_groups': sec_groups,
                'ex_metadata': node_metadata}
        if cluster_additinal_ssh_keys:
            sec_ssh_key_cloud_init = _get_cloud_init_with_sec_ssh_keys(cluster_additinal_ssh_keys)
            args['ex_userdata'] = sec_ssh_key_cloud_init
            args['ex_config_drive'] = True
        node = os_conn.create_node(**args)
    else:
        node = existing_node[0]
    return node


def _find_node_by_name(cluser_name, node_name):
    all_nodes = os_conn.list_nodes()
    node = [n for n in all_nodes if n.name == node_name]
    assert len(node) == 1 or len(node) == 0
    return node


def _get_image(img_name):
    all_images = os_conn.list_images()
    img = [i for i in all_images if i.name == img_name]
    assert len(img) == 1
    return img[0]


def _get_flavor(flavor_name):
    all_sizes = os_conn.list_sizes()
    size = [s for s in all_sizes if s.name == flavor_name]
    assert len(size) == 1
    return size[0]


def _get_primary_ssh_key(key_name):
    return os_conn.get_key_pair(key_name)


def _get_cloud_init_with_sec_ssh_keys(ssh_keys):
    cloud_init_content = """#cloud-config
ssh_authorized_keys:"""
    for sk in ssh_keys:
        cloud_init_content = cloud_init_content + "\n  - " + sk
    return cloud_init_content


def _generate_ssh_config(nodes):
    """
    """
    ssh_gateway = os_url.split(":")[1].replace("/", "").replace('identity', 'ssh').replace('-', '.')

    template = """
Host {0}
    Hostname {1}
    ProxyCommand ssh forward@{2} nc -q0 %h %p
    Port 22
    User ubuntu
    """

    cluster_ssh_config = ""
    for n in nodes:
        entry = template.format(n[0].name, n[0].private_ips[0], ssh_gateway)
        cluster_ssh_config = cluster_ssh_config + entry + "\n"

    with open("cluster_ssh_config", 'w') as f:
        f.write(cluster_ssh_config)
        f.write("\n")
    return "./cluster_ssh_config"


def _generate_host_file(n_and_ips):
    c_hosts = [n[0].name for n in n_and_ips]
    with open("cluster_hosts", 'w') as f:
        f.write(",".join(c_hosts))


def _generate_private_ips_file(n_and_ips):
    private_ips = [n[0].private_ips[0] for n in n_and_ips]
    with open("cluster_private_ips", 'w') as f:
        f.write(",".join(private_ips))


@parallel
def install_infinispan():
    """
    """
    _install_jdk()

    if not exists("infinispan.tgz"):
        run("wget '" + infinispan_package_url+"' -O infinispan.tgz")
        run("echo '" + infinispan_package_url+"' > infinispan.INFO")
    if not exists("infinispan-server-7.0.1-SNAPSHOT"):
        run("tar zxvf infinispan.tgz")
    content = _get_infinispan_config()
    tmp_file = _save_tmp_infinispan_config_file(content)
    _upload_with_scp(
        tmp_file,
        "infinispan-server-7.0.1-SNAPSHOT/standalone/configuration/infinispan-config.xml"
        )
    _install_initd_script()


def _install_jdk():
    sudo("sudo apt-get update")
    sudo("sudo apt-get install -yyf openjdk-7-jdk")


def _get_infinispan_config():
    """
    """
    with open("templates/infinispan-config_template.xml", "r") as f:
        infinispan_config_template = f.read()

    config = infinispan_config_template.replace("@NODE_IP@", env.host)
    cluster_private_ips = _get_cluster_private_ips()
    config = config.replace("@TCPPING.initial_hosts@", cluster_private_ips)
    return config


def _get_cluster_private_ips():
    with open("cluster_private_ips", 'r') as f:
        private_ips = f.read().split(",")

    result = [p_i + "[55200]" for p_i in private_ips]
    result = ",".join(result)
    return result


def _save_tmp_infinispan_config_file(content):
    tmp_file_name = "tmp_" + env.host + "infinispan-config.xml"
    with open(tmp_file_name, "w") as f:
        f.write(content)
    return tmp_file_name


def _install_initd_script():
    _upload_with_scp(
        "templates/infinispan-server_template.sh",
        "infinispan-server-7.0.1-SNAPSHOT/infinispan-server.sh"
        )
    sudo("cp ~/infinispan-server-7.0.1-SNAPSHOT/infinispan-server.sh /etc/init.d/infinispan-server")
    sudo("chmod 755 /etc/init.d/infinispan-server")
    sudo("chown root:root /etc/init.d/infinispan-server")
    sudo("sudo update-rc.d infinispan-server defaults")
    sudo("sudo update-rc.d infinispan-server enable")


def _upload_with_scp(what, where):
    with hide('running', 'stdout'):
        local("scp -F {0} {1} {2}:{3}".format(env.ssh_config_path, what, env.host_string, where))


@parallel
def start_infinispan_service():
    sudo("sudo service infinispan-server start", pty=True)


@parallel
def stop_infinispan_service():
    sudo("sudo service infinispan-server stop", pty=True)
    
@parallel
def install_hadoop():
    """
    """
    pkg_file_name = hadoop_package_url.split("/")[-1]
    dir_name = pkg_file_name[:-len('.tar.gz')]    

    if not exists(pkg_file_name):
        run("wget '{0}' -O {1}".format(hadoop_package_url, pkg_file_name))
    if not exists(dir_name):
        run("tar zxvf {0}".format(pkg_file_name))
     
        
        
    