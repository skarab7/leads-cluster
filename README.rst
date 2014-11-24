LEADS cluster
==================

This project is based on: https://github.com/otrack/Leads-deployment.git. The project created and maintained by Pierre Sutra.


Scenario
--------------

Structure: The name of a scenario and the corresponding version of the leads-cluster:

- Infinispan setup (0.1.0)

::

   ----        ----                  ----        ---- 
  | L1 |  <-> | L1 |    <-------->  | L3 |  <-> | L4 | 
   ----        ----                  ----        ----
  ------------------                ------------------
 |    deployment    |              |    deployment    |
 |         A        |              |         B        |
  ------------------                ------------------
  
 
- Hadoop (0.2.0) 
  


- Nutch (0.3.0)
 
 
How to use it
-----------------

*Makefile* contains the most commonly used commands for this software.

What
--------------------


:: 

  [ Create VMs, tagged ] -> | Create Security Group if missing | ->  [start machines] 

    -> [install LEADS from container] -> [configure] -> [start services]

Requirements:

- create instances of *Infinispan*/*nutch*/... and tag them with specific metadata

- opening ports (*security groups*)
 
- configuring *Infinispan* (overwriting), spawning manually new instances, connecting them (?)

- quick patch process:

 - quick-line for updating target running instance

- discover all running instances with type based on instance metadata


Development 
----------------

Setup
~~~~~~~~~

Recommended way: virutalenv + virtualenvwrapper.

1. Init the virutalenv

::

  make init_virtualenv
  workon leads-cluster



Weapon of choice
~~~~~~~~~~~~~~~~~

- fabric
- cloud-init scripts / docker to create software artifacts early in the process
  


