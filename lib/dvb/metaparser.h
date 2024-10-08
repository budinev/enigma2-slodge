#ifndef __lib_dvb_metaparser_h
#define __lib_dvb_metaparser_h

#include <string>
#include <lib/dvb/idvb.h>

class eDVBMetaParser
{
public:
	eDVBMetaParser();
	int parseFile(const std::string &basename);
	int parseMeta(const std::string &filename);
	int parseRecordings(const std::string &filename);
	int updateMeta(const std::string &basename);

	eServiceReferenceDVB m_ref;
	int m_data_ok, m_time_create, m_packet_size, m_scrambled;
	std::string m_name, m_description, m_tags, m_service_data, m_prov;
	long long m_filesize, m_length;
};

#endif
