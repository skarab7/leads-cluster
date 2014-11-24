
_VIRTUALWRAPPERENV_NAME='leads-cluster'

INFINISPAN_ARCHIVE_AUTH_URL=https://identity-hamm5.cloudandheat.com:5000/v2.0
INFINISPAN_ARCHIVE_TENANT=LEADS

INFINISPAN_ARCHIVE_OBJECT=/v1/AUTH_73e8d4d1688f4e1f86926d4cb897091f/infinispan/infinispan-server-7.0.1-SNAPSHOT.tgz
INFINISPAN_ARCHIVE_SWIFT_ENDPOINT=https://object-hamm5.cloudandheat.com:8080

# default value 30 days
VALIDITY_OF_TEMPURL_SEC=24*60*60*30

_SSH_CONFIG_FILE=cluster_ssh_config

####
# virtualenv initialization 
####
init_virtualenv:
	. $$(which virtualenvwrapper.sh) ; \
	mkvirtualenv $(_VIRTUALWRAPPERENV_NAME) ; \
	workon $(_VIRTUALWRAPPERENV_NAME); \
	pip install -U -r requirements.txt; deactivate 

cluster_create:
	fab create_cluster

cluster_install_infinispan:
	fab -H $$(<cluster_hosts) install_infinispan --ssh-config-path=$(_SSH_CONFIG_FILE)

cluster_start_infinispan:
	fab -H $$(<cluster_hosts) start_infinispan_service --ssh-config-path=$(_SSH_CONFIG_FILE)	

cluster_stop_infinispan:
	fab -H $$(<cluster_hosts) stop_infinispan_service --ssh-config-path=$(_SSH_CONFIG_FILE)	

cluster_install_hadoop:
	fab -H $$(<cluster_hosts) install_hadoop --ssh-config-path=cluster_ssh_config

cluster_start_hadoop:
	fab -H $$(<cluster_hosts) start_hadoop_service  --ssh-config-path=cluster_ssh_config

cluster_stop_hadoop:
	fab -H $$(<cluster_hosts) stop_hadoop_service  --ssh-config-path=cluster_ssh_config

# export LEADS_CLUSTER_ADD_SSH_KEYS="$(<id_rsa.pub)"
deploy_additional_keys:
	if [ -z $${LEADS_CLUSTER_ADD_SSH_KEYS} ]; then echo "The environment variable LEADS_CLUSTER_ADD_SSH_KEYS must be set"; exit 1; fi; \
	fab -H $$(<cluster_hosts) deploy_additioanl_ssh_keys --ssh-config-path=$(_SSH_CONFIG_FILE)	

# You can geneate the key with openssl
# export MY_SECRET_KEY=$(openssl rand -hex 16)
# make swift_repo_get_temp_url_infinispan_package SWIFT_TEMPURL_KEY=${MY_SECRET_KEY}
swift_repo_get_temp_url_infinispan_package: 	
	if test '$(SWIFT_TEMPURL_KEY)' = ""; then echo "SWIFT_TEMPURL_KEY must be set"; exit 1; fi; \
	unset OS_TENANT_ID ; \
	swift --os-project-name $(INFINISPAN_ARCHIVE_TENANT) --os-auth-url $(INFINISPAN_ARCHIVE_AUTH_URL) post -m "Temp-URL-Key: $(SWIFT_TEMPURL_KEY)" ; \
	swift --os-project-name $(INFINISPAN_ARCHIVE_TENANT) --os-auth-url $(INFINISPAN_ARCHIVE_AUTH_URL) \
	tempurl GET $$(echo '$(VALIDITY_OF_TEMPURL_SEC)' | bc) $(INFINISPAN_ARCHIVE_OBJECT)  $(SWIFT_TEMPURL_KEY) | xargs -I {} echo $(INFINISPAN_ARCHIVE_SWIFT_ENDPOINT){}




