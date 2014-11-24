LEADS cluster
==================

The project goal is to provide an easy way to setup a cluster for FP7 EU LEADS project (http://www.leads-project.eu). 

This project is based on: https://github.com/otrack/Leads-deployment.git. A project created and maintained by Pierre Sutra.

**Main git repo is https://github.com/skarab7/leads-cluster.git.**

Scenario
--------------

Structure: The name of a scenario and the corresponding version of the leads-cluster:

- leads-cluster setup (1.0.0)

  N-node cluster in one Cloud&Heat cloud

  ::

     ----        ----      
    | L1 |  <-> | L2 |    
     ----        ----     
    ------------------     
   |    deployment    |
   |         A        |
    ------------------ 

 
- Hadoop (1.1.0) 

  Install Hadoop

- Nutch (1.2.0)

  Install Nutch

- Infinispan setup (2.0.0)
 
  Cross deployment (microclouds) deployment

  ::
  
     ----        ----                  ----        ---- 
    | L1 |  <-> | L2 |    <-------->  | L3 |  <-> | L4 | 
     ----        ----                  ----        ----
    ------------------                ------------------
   |    deployment    |              |    deployment    |
   |         A        |              |         B        |
    ------------------                ------------------

How to use it
-----------------

*Makefile* is the entry point for this project.

Workflow
~~~~~~~~~~~

:: 

  [ Create VMs, tagged ] -> [ Create Security Group if missing ] ->  [start machines] 

    -> [install LEADS from container] -> [configure] -> [start services]

Tasks
~~~~~~~~~~~~~~~

Please use virutalenv and virtualenvwrapper to manage your python libraries.

1. Init the virutalenv

  ::

    make init_virtualenv
    workon leads-cluster

  **You need to enable virtualenv to run all tasks described below.**

2. Create cluster
   
  This task will create nodes only if nodes do not exist. It is idempotent.  
 
  .. code:: bash

    # you need to load your openrc 
    source openrc

    # specify number of nodes:
    export LEADS_CLUSTER_NUM_OF_NODES=2

    # you need to specify ssh-pair that you want to use
    # to setup LEADS nodes through ssh
    export LEADS_CLUSTER_PRIMARY_SSH_KEY=ssh-pair-name

    # list of secondary ssh-key that are injected to the node
    # thought clout-init script
    export LEADS_CLUSTER_ADD_SSH_KEYS="ssh-rsa AAA...,ssh-rsa AAA..."
    # 
    make cluster_create


  Optional options through environment variables:

    - LEADS_CLUSTER_NAME, default value: leads_m24_cluster

  This task also generates the following files:

    - cluster_hosts - host names of nodes in the cluster
    - cluster_private_ips - private ips of nodes in the cluster
    - cluster_ssh_config - ssh config, so you can easily to connect to them with ssh:
    
      .. code:: bash

        ssh leads_m24_cluster_node_0 -F cluster_ssh_config


3. Install infinispan
   
  This script requires *cluster_hosts*, *cluster_private_ips*, and *cluster_ssh_config*. So, you need to run the previous step.

  .. code:: bash
  
    make cluster_install_infinispan

4. Start infinispan 
 
  In parallel, the infinispan service is stopped on all the cluster nodes

  .. code:: bash
  
    make cluster_start_infinispan

5. Stop infinispan 
 
  In parallel, the infinispan service is started on all the cluster nodes
     
  .. code:: bash

    make cluster_stop_infinispan


6. Install hadoop
  
  In the current version, hadoop is installed on the same nodes as infinispan. 
  We distringuish: master (running: *namenode*, *datanode*, *resource manager*, *node manager*) and slave (*node manager*).

  In the next versions, we will move it to separate nodes. We also introduce a separate *resource manager*.

  .. code:: bash

    # you can specify which node should be the hadoop master
    # default is 0
    export LEADS_CLUSTER_HADOOP_MASTER_NODE_ID=0 
     
    # you can specif which nodes are slaves
    # default is 1
    export LEADS_CLUSTER_HADOOP_SLAVE_NODE_IDS=1

    make cluster_install_hadoop

7. Start hadoop
   
  .. code:: bash
     
    make cluster_start_hadoop

8. Stop hadoop
   
  .. code:: bash
     
    make cluster_stop_hadoop


Helpers
~~~~~~~~~~~~~~~

1. Deploying new infinispan archive
    
  The infinispan, that we installed, is download from an *URL* (currently hard-coded in fabric.py). Below, you will find instruction 
  how to deploy new version of infinispan to swift container and generate a *URL* to access it during installation.

  1. Upload infinispan-server-7.0.1-SNAPSHOT.tgz to *infinispan* container.
     
     .. code:: bash

        # openrc of the microcloud with the *infinispan* container (see Makefile for the default)
     	source openrc
     	swift upload infinispan infinispan-server-7.0.1-SNAPSHOT.tgz

     You can also use a tool with nice UI, such as: cyberduck.
   
  2. Generate temp-url to access infinispan-server-7.0.1-SNAPSHOT.tgz without password (so called *temp-url*)

    .. code:: bash
  
      export OS_USERNAME=...
      export OS_PASSWORD=...

      # select the current the temp-key 
      export MY_SECRET_KEY=$(swift stat | grep Temp-Url | cut -d":" -f2 | tr -d ' ')
      # or generate new one
      export MY_SECRET_KEY=$(openssl rand -hex 32)

      make swift_repo_get_temp_url_infinispan_package SWIFT_TEMPURL_KEY=${MY_SECRET_KEY}
     
  3. Modify *infinispan_package_url* in fabric.py
     
     .. code:: python

       infinispan_package_url='https://object-hamm5.cloudandheat.com:8080/'\
                              'v1/AU...

 2. Importing new ssh_keys to the running nodes

  .. code:: bash

    export LEADS_CLUSTER_ADD_SSH_KEYS="$(<id_rsa.pub)"
    make deploy_additional_keys

Weapon of choice
~~~~~~~~~~~~~~~~~

- fabric - most familiar to project partners
- cloud-init scripts / docker to create software artifacts early in the process

Notes
--------------------

Requirements:

- create instances of *Infinispan*/*nutch*/... and tag them with specific metadata

- opening ports (*security groups*)
 
- configuring *Infinispan* (overwriting), spawning manually new instances, connecting them (?)

- the cluster nodes should discover other nodes


Resources
-------------

- Cloud&Heat Cloud manuals: https://www.cloudandheat.com/en/support.html

  


