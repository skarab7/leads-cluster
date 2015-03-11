from fabric.contrib.files import exists, append, contains
from fabric.contrib import files
from fabric.api import run, env, sudo, local, cd, settings
from fabric.api import hide, parallel, roles, hosts, serial
from fabric.context_managers import shell_env
from fabric.utils import error
import os

from libcloud.compute.types import Provider
from libcloud.compute.providers import get_driver
import libcloud.security
from prettytable import PrettyTable


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


def _get_node_name(node_name_prefix, node_id):
    return node_name_prefix + "-" + str(node_id)


env.forward_agent = True
env.use_ssh_config = True

os_user = os.environ["OS_USERNAME"]
os_tenant_name = os.environ["OS_TENANT_NAME"]
os_password = os.environ["OS_PASSWORD"]
os_url = os.environ["OS_AUTH_URL"]+"/tokens"

cluster_num_of_nodes = int(os.environ["LEADS_CLUSTER_NUM_OF_NODES"])
cluster_name = _get_env_value("LEADS_CLUSTER_NAME", "leads-m24-cluster")

cluster_security_group_name = cluster_name + "_internal"

# infinispan - 54200 and 55200
# hadoop - 9000 and 9001 and 50070 (NameNode) and 8088 (resourcemanager)
cluster_port_communication = ['54200', '55200', '22', '9000', '9001', '50070',
                              '8088', '19888', '10020']

cluster_external_access_sg_name = cluster_name + "_external_access"
cluster_external_access_ports = ['22']

# the openstack primary
cluster_primary_ssh_key = _get_env_value("LEADS_CLUSTER_PRIMARY_SSH_KEY", "wb-new-key")
# injected using cloud-init
# on C&H, the ssh key must be imported to the installation
# otherwise you can
cluster_additinal_ssh_keys = _get_env_array("LEADS_CLUSTER_ADD_SSH_KEYS", [], ',')

node_name_prefix = cluster_name + "-node"
node_flavor = "cloudcompute.s"
image_name = "Ubuntu 14.04 LTS x64"
node_metadata = {"leads_cluster_name":  cluster_name}

infinispan_package_url = 'https://object-hamm5.cloudandheat.com:8080/'\
                         'v1/AUTH_73e8d4d1688f4e1f86926d4cb897091f/infinispan/infinispan-server-7.0.1-SNAPSHOT.tgz?'\
                         'temp_url_sig=76fcfe3e623edea4642e443ba5ff04e076395b85&'\
                         'temp_url_expires=1419376046'

hadoop_package_url = 'https://archive.apache.org/dist/hadoop/core/hadoop-2.5.2/hadoop-2.5.2.tar.gz'

hadoop_master_node_id = _get_env_value("LEADS_CLUSTER_HADOOP_MASTER_NODE_ID", 0)
hadoop_master_node = _get_node_name(node_name_prefix, str(hadoop_master_node_id))
hadoop_slave_node_ids = _get_env_array("LEADS_CLUSTER_HADOOP_SLAVE_NODE_IDS", [1], ",")
hadoop_slave_nodes = [_get_node_name(node_name_prefix, s) for s in hadoop_slave_node_ids]

env.roledefs = {
    'masters': [hadoop_master_node],
    'slaves': hadoop_slave_nodes
}


Driver = get_driver(Provider.OPENSTACK)
os_conn = Driver(os_user, os_password,
                 ex_tenant_name=os_tenant_name,
                 ex_force_auth_url=os_url,
                 ex_force_auth_version='2.0_password')

libcloud.security.VERIFY_SSL_CERT = False


# fabric roles works only on env.host
# for us it is simplier to use env.host_string
def roles_host_string_based(*args):
    supported_roles = args

    def new_decorator(func):
        def func_wrapper(*args, **kwargs):
            for role in supported_roles:
                role_hosts = [r[1] for r in env.roledefs.items() if r[0] == role][0]
                if env.host_string in role_hosts:
                    func(*args, **kwargs)
        return func_wrapper
    return new_decorator


def create_cluster():
    external_sec_group = _create_external_access_sg(cluster_external_access_sg_name)
    internal_sec_group = _create_cluster_internal_sg(cluster_security_group_name)

    sec_groups = [external_sec_group, internal_sec_group]
    # create a VM
    nodes = []
    for i in range(0, cluster_num_of_nodes):
        node_name = _get_node_name(node_name_prefix, i)
        n = _create_instance(cluster_name, node_name, sec_groups)
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
def deploy_additioanl_ssh_keys():
    authorized_file = "~/.ssh/authorized_keys"
    for k in cluster_additinal_ssh_keys:
        if not contains(authorized_file, k.strip()):
            append(authorized_file, "\n")
            append(authorized_file, k.strip())


@roles_host_string_based('masters', 'slaves')
@parallel
def install_hadoop():
    """
    """
    pkg_file_name = _get_hadoop_pkg_name(hadoop_package_url)
    dir_name = _get_hadoop_name(hadoop_package_url)

    if not exists(pkg_file_name):
        run("wget '{0}' -O {1}".format(hadoop_package_url, pkg_file_name))
    if not exists(dir_name):
        run("tar zxvf {0}".format(pkg_file_name))

    hadoop_home = "/home/ubuntu/{0}".format(dir_name)
    _hadoop_configure(hadoop_home)


def _get_hadoop_pkg_name(url):
    return url.split("/")[-1]


def _get_hadoop_name(url):
    pkg_file_name = _get_hadoop_pkg_name(url)
    return pkg_file_name[:-len('.tar.gz')]


def _hadoop_configure(hadoop_home):
    hadoop_master_priv_ip = get_node_private_ip(hadoop_master_node)
    _hadoop_heap_configure(hadoop_home)
    _hadoop_change_map_red_site(hadoop_home, hadoop_master_node)
    _hadoop_change_core_site(hadoop_home, hadoop_master_priv_ip)
    _hadoop_change_yarn_site(hadoop_home, hadoop_master_node)
    _hadoop_change_HDFS_site(hadoop_home, hadoop_master_node)
    _hadoop_change_masters(hadoop_home, hadoop_master_node)
    _hadoop_change_slaves(hadoop_home, env.roledefs['slaves'])
    _hadoop_prepare_etc_host()


def get_node_private_ip(node_name):
    ns = _find_node_by_name(cluster_name, node_name)

    if not ns:
        error("No node is running with name {0}!".format(node_name))
    else:
        node = ns[0]
        return node.private_ips[0]


@roles_host_string_based('masters', 'slaves')
def _hadoop_heap_configure(hadoop_home, new_heap_size=1000, old_heap_size=2000):
    """
    Le Quoc Do - SE Group TU Dresden contribution
    """
    filename = hadoop_home + '/etc/hadoop/hadoop-env.sh'
    before = 'HADOOP_HEAPSIZE=' + str(new_heap_size)
    after = 'HADOOP_HEAPSIZE=' + str(old_heap_size)
    files.sed(filename, before, after, limit='')
    files.uncomment(filename, 'HADOOP_HEAPSIZE')


@roles_host_string_based('masters', 'slaves')
def _hadoop_change_map_red_site(hadoop_home, master, map_task='8', reduce_task='6'):
    """
    Based on input from Le Quoc Do - SE Group TU Dresden contribution
    """
    before = '<configuration>'
    after = """
<configuration>
    <property>
        <name>mapred.job.tracker</name>
        <value>{0}:9001</value>
    </property>

    <property>
        <name>mapred.map.tasks</name>
        <value>{1}</value>
    </property>

    <property>
        <name>mapred.reduce.tasks</name>
        <value>{2}</value>
    </property>

    <property>
        <name>mapred.system.dir</name>
        <value>{3}/hdfs/mapreduce/system</value>
    </property>

    <property>
        <name>mapred.local.dir</name>
        <value>{3}/hdfs/mapreduce/local</value>
    </property>

    <property>
        <name>mapreduce.framework.name</name>
        <value>yarn</value>
    </property>
    """.format(master, map_task, reduce_task,  hadoop_home)

    with cd(hadoop_home + '/etc/hadoop/'):
        run('cp mapred-site.xml.template mapred-site.xml')
        filename = 'mapred-site.xml'
        files.sed(filename, before, after.replace("\n", "\\n"), limit='')


@roles_host_string_based('masters', 'slaves')
def _hadoop_change_core_site(hadoop_home, master_ip):
    """
    Based on input from Le Quoc Do - SE Group TU Dresden contribution
    """
    content = """
<configuration>
    <property>
        <name>hadoop.tmp.dir</name>
        <value>{0}/hdfs</value>
    </property>
    <property>
        <name>fs.defaultFS</name>
        <value>hdfs://{1}:9000</value>
    </property>

    <property>
        <name>fs.default.name</name>
        <value>hdfs://{1}:9000</value>
    </property>

    <property>
        <name>mapred.job.tracker</name>
        <value>{1}:9001</value>
    </property>
</configuration>""".format(hadoop_home, master_ip)

    filename = 'core-site.xml'
    with cd(hadoop_home + '/etc/hadoop/'):
        run("rm -f {0}; touch {0}".format(filename))
        files.append(filename, content)


@roles_host_string_based('masters', 'slaves')
def _hadoop_change_yarn_site(hadoop_home, master):
    filename = 'yarn-site.xml'

    content = """
<configuration>
    <property>
        <name>yarn.nodemanager.aux-services</name>
        <value>mapreduce_shuffle</value>
    </property>
</configuration>"""

    with cd(hadoop_home + '/etc/hadoop/'):
        run("rm -f {0}; touch {0}".format(filename))
        files.append(filename, content)


@roles_host_string_based('masters', 'slaves')
def _hadoop_change_HDFS_site(hadoop_home, master, replica='1', xcieversmax='10096'):
    """
    Based on input from Le Quoc Do - SE Group TU Dresden contribution
    """
    filename = 'hdfs-site.xml'
    content = """
<configuration>
    <property>
        <name>dfs.name.dir</name>
        <value>file://{0}/hdfs/name</value>
    </property>
    <property>
        <name>dfs.data.dir</name>
        <value>file://{0}/hdfs/data</value>
    </property>

    <property>
        <name>dfs.replication</name>
        <value>{1}</value>
    </property>

    <property>
        <name>dfs.datanode.max.xcievers</name>
        <value>{2}</value>
    </property>
</configuration>
""".format(hadoop_home, replica,  xcieversmax)

    with cd(hadoop_home + '/etc/hadoop/'):
        run("rm -f {0}; touch {0}".format(filename))
        files.append(filename, content)


@roles_host_string_based('masters', 'slaves')
def _hadoop_change_masters(hadoop_home, master):
    """
    Le Quoc Do - SE Group TU Dresden contribution
    """
    filename = 'masters'

    with cd(hadoop_home + '/etc/hadoop'):
        run("rm -f masters; touch masters")
        files.append(filename, master)


@roles_host_string_based('masters', 'slaves')
def _hadoop_change_slaves(hadoop_home, slaves):
    """
    Le Quoc Do - SE Group TU Dresden contribution
    """
    filename = 'slaves'
    before = 'localhost'
    after = ''
    for slave in slaves:
        after = after + slave + '\\n'
    with cd(hadoop_home + '/etc/hadoop'):
        files.sed(filename, before, after, limit='')


@roles_host_string_based('masters', 'slaves')
def _hadoop_prepare_etc_host():
    with open('cluster_hosts', 'r') as f:
        c_hostnames = f.read().split(',')
    with open('cluster_private_ips', 'r') as f:
        c_priv_ips = f.read().split(',')
    for i in range(0, len(c_hostnames)):
        entry = c_priv_ips[i] + " " + c_hostnames[i]
        if not files.contains('/etc/hosts', entry):
            files.append('/etc/hosts', entry, use_sudo=True)


def _get_hadoop_home():
    return "/home/ubuntu/{0}".format(_get_hadoop_name(hadoop_package_url))


@roles_host_string_based('masters', 'slaves')
@serial
def start_hadoop_service():
    """
    Hadoop: start service
    """
    _hadoop_command_namenode("start")
    _hadoop_command_datanode("start")
    _hadoop_command_resource_mgmt("start")
    _hadoop_command_node_manager("start")


def _command_hadoop_service(command):
    hadoop_home = _get_hadoop_home()
    with cd(hadoop_home):
            run("./sbin/{0}-yarn.sh".format(action))


@roles_host_string_based('masters')
def _hadoop_command_namenode(action):
    _execute_hadoop_command('$HADOOP_PREFIX/sbin/hadoop-daemon.sh --config $HADOOP_CONF_DIR'
                            ' --script hdfs ' + action + ' namenode')


def _execute_hadoop_command(cmd):
    hadoop_home = _get_hadoop_home()

    with shell_env(JAVA_HOME='/usr/lib/jvm/java-7-openjdk-amd64',
                   HADOOP_PREFIX=hadoop_home,
                   HADOOP_CONF_DIR=hadoop_home + "/etc/hadoop",
                   HADOOP_YARN_HOME=hadoop_home):
        run(cmd)


@roles_host_string_based('masters')
def _hadoop_command_datanode(action):
    _execute_hadoop_command('$HADOOP_PREFIX/sbin/hadoop-daemon.sh --config $HADOOP_CONF_DIR'
                            ' --script hdfs ' + action + ' datanode')


@roles_host_string_based('masters')
def _hadoop_command_resource_mgmt(action):
    _execute_hadoop_command('$HADOOP_YARN_HOME/sbin/yarn-daemon.sh'
                            ' --config $HADOOP_CONF_DIR ' + action + ' resourcemanager')


@roles_host_string_based('masters', 'slaves')
def _hadoop_command_node_manager(action):
    _execute_hadoop_command('$HADOOP_YARN_HOME/sbin/yarn-daemon.sh'
                            ' --config $HADOOP_CONF_DIR ' + action + ' nodemanager')


@serial
def stop_hadoop_service():
    """
    Hadoop: stop service
    """
    _hadoop_command_namenode("stop")
    _hadoop_command_datanode("stop")
    _hadoop_command_resource_mgmt("stop")
    _hadoop_command_node_manager("stop")


@roles_host_string_based('masters')
def hadoop_format():
    hadoop_home = _get_hadoop_home()

    with settings(warn_only=True):
        with cd(hadoop_home):
            with shell_env(JAVA_HOME='/usr/lib/jvm/java-7-openjdk-amd64',
                           HADOOP_PREFIX=hadoop_home):
                run('echo "Y" | bin/hdfs namenode -format')
                run('bin/hdfs datanode -regular')


def show_running_leads_clusters():
    """
    """
    x = PrettyTable(["Cluster name", "Node name", "Node UUID"])
    for inst in os_conn.list_nodes():
        md = os_conn.ex_get_metadata(inst)
        if "leads_cluster_name" in md:
            row = []
            row.append(md["leads_cluster_name"])
            row.append(inst.name)
            row.append(inst.id)
            x.add_row(row)
    print x
