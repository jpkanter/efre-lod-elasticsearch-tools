#!/usr/bin/python3
# -*- coding: utf-8 -*-
from rdflib import URIRef
import traceback
from uuid import uuid4
from multiprocessing import Pool, Manager,current_process,Process,cpu_count
import elasticsearch
import json
#import urllib.request
import codecs
import argparse
import sys
import io
import os.path
import mmap
import requests
import siphash
import re
from es2json import esgenerator, esidfilegenerator, esfatgenerator, ArrayOrSingleValue, eprint, litter, isint

es=None
generate=False
lookup_es=None

def uniq(lst):
    last = object()
    for item in lst:
        if item == last:
            continue
        yield item
        last = item

def getiso8601(date):
    p=re.compile(r'[\d|X].\.[\d|X].\.[\d|X]*') #test if D(D).M(M).Y(YYY)
    m=p.match(date)
    datestring=""
    if m:
        slices=list(reversed(date.split('.')))
        if isint(slices[0]):
            datestring+=str(slices[0])
        for slice in slices[1:]:
            if isint(slice):
                datestring+="-"+str(slice)
            else:
                break
        return datestring
    else:
        return date #was worth a try
    
def dateToEvent(date,schemakey):
    if '-' in date:
        dates=date.split('-')
        if date[0]=='[' and date[-1]==']': #oh..
            return str("["+dateToEvent(date[1:-1],schemakey)+"]")        
        if "irth" in schemakey: # (date of d|D)eath(Dates)
                return getiso8601(dates[0])
        elif "eath" in schemakey: #(date of d|D)eath(Date)
            if len(dates)==2:
                return getiso8601(dates[1])
            elif len(dates)==1: 
                return None # still alive! congrats
        else:
            return date

def handlesex(record,key,entity):
    for v in key:
        marcvalue=getmarc(v,record,entity)
        if isinstance(marcvalue,list):
            marcvalue=marcvalue[0]
    if isint(marcvalue):
        marcvalue=int(marcvalue)
    if marcvalue==0:
        return "Unknown"
    elif marcvalue==1:
        return "Male"
    elif marcvalue==2:
        return "Female"
    elif marcvalue==9:
        return None


isil2sameAs = {
    "DE-576":"http://swb.bsz-bw.de/DB=2.1/PPNSET?PPN=",
    "DE-588":"http://d-nb.info/gnd/",
    "DE-601":"http://gso.gbv.de/PPN?PPN=",
    "(DE-576)":"http://swb.bsz-bw.de/DB=2.1/PPNSET?PPN=",
    "(DE-588)":"http://d-nb.info/gnd/",
    "(DE-601)":"http://gso.gbv.de/PPN?PPN=",
    "DE-15":"Univeristätsbibliothek Leipzig",
    "DE-14":"Sächsische Landesbibliothek – Staats- und Universitätsbibliothek Dresden",
}

marc2relation = {
    "VD-16 Mitverf": "contributor",
    "v:Mitverf": "contributor",
    "v:Co-Autor": "contributor",
    "v:Doktorvater": "contributor",
    "v:Illustrator": "contributor",
    "v:Übersetzer": "contributor",
    "v:Biograf": "contributor",
    "v:Förderer": "contributor",
    "v:Berater": "contributor",
    "v:hrsg": "contributor",
    "v:Mitautor": "contributor",
    "v:Partner": "contributor",
    
    "v:Tocher": "children",            #several typos in SWB dataset
    "tochter": "children",
    "Z:Tochter":"children",
    "Sohn": "children",
    "v:Nachkomme": "children",
    "v:zweites Kind": "children",
    
    "v:Gattin": "spouse",
    "v:Gatte": "spouse",
    "v:Gemahl": "spouse",
    "Ehe": "spouse",
    "Frau": "spouse",
    "Mann": "spouse",
    
    "v:Jüngster Bruder": "sibling",
    "Bruder": "sibling",
    "v:Zwilling": "sibling",
    "Schwester": "sibling",
    "v:Halbschwester": "sibling",
    "v:Halbbruder": "sibling",
    "Vater": "parent",
    "Z:Vater":"parent",
    "v:Stiefvater": "parent",
    "Mutter": "parent",
    
    "Nachfolger": "follows",
    "Vorgänger": "follows",
    
    "v:Vorfahr": "relatedTo",
        
    "v:Schüler": "relatedTo",        
    "Lehrer": "relatedTo",        
    "v:frühere Ehefrau": "relatedTo",
    "v:Schwager": "relatedTo",        
    "v:Ur": "relatedTo",          
    "v:Muse": "relatedTo",
    "v:Nachfahre": "relatedTo",         
    "v:Groß": "relatedTo",    
    "v:Langjähriger Geliebter": "relatedTo",    
    "v:Lebensgefährt": "relatedTo",    
    "v:Nichte": "relatedTo",
    "v:Stiefnichte": "relatedTo",
    "v:Neffe": "relatedTo",
    "v:Onkel": "relatedTo",
    "v:Tante": "relatedTo",
    "v:Verlobt": "relatedTo",
    "v:Vorfahren": "relatedTo",
    "v:Vetter": "relatedTo",
    "v:Tauf": "relatedTo",
    "v:Pate": "relatedTo",
    "v:Schwägerin": "relatedTo",
    "v:Schwiegervater": "relatedTo",
    "v:Schwiegermutter": "relatedTo",
    "v:Schwiegertochter": "relatedTo",
    "v:Schwiegersohn": "relatedTo",
    "v:Enkel": "relatedTo",
    "v:Mätresse": "relatedTo",
    "Freund": "knows",
    "v:Großvater": "relatedTo",
    "v:Cousin": "relatedTo",
    "v:Lebenspartner": "relatedTo",
    "v:Berater und Freund": "relatedTo",
    "v:Geliebte": "relatedTo",
    "v:Modell und Lebensgefährtin":"relatedTo",
    "v:Liebesbeziehung":"relatedTo",
    
    "v:publizistische Zusammenarbeit und gemeinsame öffentliche Auftritte": "colleague",
    "v:Sekretär": "colleague", 
    "v:Privatsekretär": "colleague", 
    "v:Kolleg": "colleague", 
    "v:Mitarbeiter": "colleague", 
    "v:Kommilitone": "colleague", 
    "v:Zusammenarbeit mit": "colleague", 
    "v:gemeinsames Atelier": "colleague", 
    "v:Geschäftspartner": "colleague" , 
    "v:musik. Partnerin": "colleague" ,
    "v:Künstler. Partner": "colleague" ,  
    "assistent": "colleague",
    
    #see also http://www.dnb.de/SharedDocs/Downloads/DE/DNB/standardisierung/inhaltserschliessung/gndCodes.pdf?__blob=publicationFile
    "4:adel":"honorificPrefix",
    "4:adre":"recipent",
    "4:adue":"parentOrganization",
    "4:affi":"affiliation",
    #"4:akad":"honorificPrefix",
    "4:akti":"hasProfession",
    "4:bezf":"relatedTo",
    "4:bezb":"colleague",
    "4:beza":"knows",
    "4:bete": "contributor",
    "4:rela":"knows",
    "4:affi":"knows",
    "4:aut1":"author",
}

def gnd2uri(string):
    try:
        if isinstance(string,list):
            for n,uri in enumerate(string):
                string[n]=gnd2uri(uri)
            return string
        if string and "(DE-" in string:
            if isinstance(string,list):
                ret=[]
                for st in string:
                    ret.append(gnd2uri(st))
                return ret
            elif isinstance(string,str):
                return uri2url(string.split(')')[0][1:],string.split(')')[1])
    except:
        return 

def uri2url(isil,num):
    if isil and num and isil in isil2sameAs:
        return str(isil2sameAs.get(isil)+num)
    else:
        return str("("+isil+")"+num)    #bugfix for isil not be able to resolve for sameAs, so we give out the identifier-number

def id2uri(string,entity):
    return "http://data.slub-dresden.de/"+entity+"/"+string
    
def getmarcid(record,regex,entity): # in this function we try to get PPNs by fields defined in regex. regex should always be a list and the most "important" field on the left. if we found a ppn in a field, we'll return it
    for reg in regex:           
        ret=getmarc(record,reg,entity)
        if ret:
            return ret

def get_or_generate_id(record,entity):
    global es
    #set generate to True if you're 1st time filling a infrastructure from scratch!
    # replace args.host with your adlookup service :P
    if generate:
        identifier = None
    else:
        marcid=getmarcid(record,["980..a","001"],entity)
        if record.get("003") and marcid:
            ppn=gnd2uri("("+str(getisil(record,"003",entity))+")"+str(marcid))
            if ppn:
                try:
                    search=lookup_es.search(index=entity,doc_type="schemaorg",body={"query":{"term":{"sameAs.keyword":ppn}}},_source=False)
                    if search.get("hits").get("total")>0:
                        newlist = sorted(search.get("hits").get("hits"), key=lambda k: k['_score'],reverse=True) 
                        identifier=newlist[0].get("_id")
                    else:
                        identifier=None
                except Exception as e:
                    with open("errors.txt",'a') as f:
                        traceback.print_exc(file=f)
                    identifier=None
            else:
                identifier=None
        else:
            identifier=None
        
    if identifier:
        return id2uri(identifier,entity)
    else:
        return id2uri(siphash.SipHash_2_4(b'slub-dresden.de/').update(uuid4().bytes).hexdigest().decode('utf-8').upper(),entity)

def getisil(record,regex,entity):
    isil=getmarc(record,regex,entity)
    if isinstance(isil,str) and isil in isil2sameAs:
        return isil
    elif isinstance(isil,list):
        for item in isil:
            if item in isil2sameAs:
                return item

def getmarc(record,regex,entity):
    if "+" in regex:
        marcfield=regex[:3]
        if marcfield in record:
            subfields=regex.split(".")[-1].split("+")
            data=None
            for array in record.get(marcfield):
                for k,v in array.items():
                    sset={}
                    for subfield in v:
                        for subfield_code in subfield:
                            sset[subfield_code]=subfield[subfield_code]
                    fullstr=""
                    for sf in subfields:
                        if sf in sset:
                            if fullstr:
                                fullstr+=". "
                            if isinstance(sset[sf],str):
                                fullstr+=sset[sf]
                            elif isinstance(sset[sf],list):
                                fullstr+=". ".join(sset[sf])
                    if fullstr:
                        data=litter(data,fullstr)
            if data:
                return ArrayOrSingleValue(data)
    else:
        ret=[]
        if isinstance(regex,str):
            regex=[regex]
        for string in regex:
            if string[:3] in record:
                ret=litter(ret,ArrayOrSingleValue(list(getmarcvalues(record,string,entity))))
        if ret:
            if isinstance(ret,list):    #simple deduplizierung via uniq() 
                ret = list(uniq(ret))
            return ArrayOrSingleValue(ret)

def getmarcvalues(record,regex,entity):
        if len(regex)==3 and regex in record:
            yield record.get(regex)
        #eprint(regex+":\n"+str(record)+"\n\n") ### beware! hardcoded traverse algorithm for marcXchange record encoded data !!! ### temporary workaround: http://www.smart-jokes.org/programmers-say-vs-what-they-mean.html
        else:
            record=record.get(regex[:3]) # = [{'__': [{'a': 'g'}, {'b': 'n'}, {'c': 'i'}, {'q': 'f'}]}]
            if isinstance(record,list):  
                for elem in record:
                    if isinstance(elem,dict):
                        for k in elem:
                            if isinstance(elem[k],list):
                                for final in elem[k]:
                                    if regex[-1] in final:
                                        yield final.get(regex[-1])

def handle_about(jline,key,entity):
    ret=[]
    for k in key:
        if k=="936" or k=="084":
            data=getmarc(jline,k,None)
            if isinstance(data,list):
                for elem in data:
                    ret.append(handle_single_rvk(elem))
            elif isinstance(data,dict):
                ret.append(handle_single_rvk(data))
        elif k=="082" or k=="083":
            data=getmarc(jline,k+"..a",None)
            if isinstance(data,list):
                for elem in data:
                    if isinstance(elem,str):
                        ret.append(handle_single_ddc(elem))
                    elif isinstance(elem,list):
                        for final_ddc in elem:
                            ret.append(handle_single_ddc(final_ddc))
            elif isinstance(data,dict):
                ret.append(handle_single_ddc(data))
            elif isinstance(data,str):
                ret.append(handle_single_ddc(data))
        elif k=="655":
            data=get_subfield(jline,k,entity)
            if isinstance(data,list):
                for elem in data:
                    if elem.get("identifier"):
                        elem["value"]=elem.pop("identifier")
                    ret.append({"identifier":elem})
            elif isinstance(data,dict):
                if data.get("identifier"):
                    data["value"]=data.pop("identifier")
                ret.append({"identifier":data})
    if len(ret)>0:
        return ret
    else:
        return None
            
def handle_single_ddc(data):
    ddc={"identifier":{  "@type"     :"PropertyValue",
                                "propertyID":"DDC",
                                "value"     :data},
         "@id":"http://purl.org/NET/decimalised#c"+data[:3]}
    return ddc

def handle_single_rvk(data):
    sset={}
    record={}
    if "rv" in data:
        for subfield in data.get("rv"):
            for k,v in subfield.items():
                sset[k]=v
        if "0" in sset:
            record["sameAs"]=gnd2uri("(DE-576)"+sset.get("0"))
        if "a" in sset:
            record["@id"]="https://rvk.uni-regensburg.de/api/json/ancestors/"+sset.get("a")
            record["identifier"]={  "@type"     :"PropertyValue",
                                "propertyID":"RVK",
                                "value"     :sset.get("a")}
        if "b" in sset:
            record["name"]=sset.get("b")
        if "k" in sset:
            record["keywords"]=sset.get("k")
        return record
    
def handlePPN(jline,key,entity):
    return {    "@type"     :"PropertyValue",
                "propertyID":"Pica Product Number",
                "value"     :jline.get(key)}

def relatedTo(jline,key,entity):
    #e.g. split "551^4:orta" to 551 and orta
    marcfield=key[:3]
    data=[]
    if marcfield in jline:
        for array in jline[marcfield]:
            for k,v in array.items():
                sset={}
                for subfield in v:
                    for subfield_code in subfield:
                        sset[subfield_code]=subfield[subfield_code]
                #eprint(sset.get("9"),subfield4)
                if isinstance(sset.get("9"),str) and sset.get("9") in marc2relation:
                    node={}
                    node["_key"]=marc2relation[sset.get("9")]
                    if sset.get("0"):
                        uri=gnd2uri(sset.get("0"))
                        if isinstance(uri,str) and uri.startswith("http"):
                            node["sameAs"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,str):
                            node["identifier"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,list):
                            node["sameAs"]=None
                            node["identifier"]=None
                            for elem in uri:
                                if elem.startswith("http"):
                                    node["sameAs"]=litter(node["sameAs"],elem)
                                else:
                                    node["identifier"]=litter(node["identifier"],elem)
                    if sset.get("a"):
                        node["name"]=sset.get("a")
                    data.append(node)
                elif isinstance(sset.get("9"),list):
                    node={}
                    for elem in sset.get("9"):
                        if elem.startswith("v"):
                            for k,v in marc2relation.items():
                                if k.lower() in elem.lower():
                                    node["_key"]=v
                                    break
                        elif [x for x in marc2relation if x.lower() in elem.lower()]:
                            for x in marc2relation:
                                if x.lower() in elem.lower():
                                    node["_key"]=marc2relation[x]
                        elif not node.get("_key"):
                            node["_key"]="relatedTo"
                        #eprint(elem,node)
                    if sset.get("0"):
                        uri=gnd2uri(sset.get("0"))
                        if isinstance(uri,str) and uri.startswith("http"):
                            node["sameAs"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,str):
                            node["identifier"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,list):
                            node["sameAs"]=None
                            node["identifier"]=None
                            for elem in uri:
                                if elem.startswith("http"):
                                    node["sameAs"]=litter(node["sameAs"],elem)
                                else:
                                    node["identifier"]=litter(node["identifier"],elem)
                    if sset.get("a"):
                        node["name"]=sset.get("a")
                    data.append(node)
                    #eprint(node)
                    
        if data:
            return ArrayOrSingleValue(data)
        
def get_subfield_if_4(jline,key,entity):
    #e.g. split "551^4:orta" to 551 and orta
    marcfield=key.rsplit("^")[0]
    subfield4=key.rsplit("^")[1]
    data=[]
    if marcfield in jline:
        for array in jline[marcfield]:
            for k,v in array.items():
                sset={}
                for subfield in v:
                    for subfield_code in subfield:
                        sset[subfield_code]=subfield[subfield_code]
                #eprint(sset.get("9"),subfield4)
                if "9" in sset and subfield4 in sset.get("9"):
                    node={}
                    if sset.get("0"):
                        uri=gnd2uri(sset.get("0"))
                        if isinstance(uri,str) and uri.startswith("http"):
                            node["sameAs"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,str):
                            node["identifier"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,list):
                            node["sameAs"]=None
                            node["identifier"]=None
                            for elem in uri:
                                if isinstance(elem,str):
                                    if elem.startswith("http"):
                                        node["sameAs"]=litter(node["sameAs"],elem)
                                    else:
                                        node["identifier"]=litter(node["identifier"],elem)
                    if sset.get("a"):
                        node["name"]=sset.get("a")
                    data.append(node)
        if data:
            return ArrayOrSingleValue(data)

def get_subfields(jline,key,entity):
    data=[]
    if isinstance(key,list):
        for k in key:
           data=litter(data,get_subfield(jline,k,entity))
        return ArrayOrSingleValue(data)
    elif isinstance(key,string):
        return get_subfield(jline,key,entity)
    else:
        return

def get_subfield(jline,key,entity):
    #e.g. split "551^4:orta" to 551 and orta
    data=[]
    if key in jline:
        for array in jline[key]:
            for k,v in array.items():
                sset={}
                for subfield in v:
                    for subfield_code in subfield:
                        sset[subfield_code]=subfield[subfield_code]
                #eprint(sset.get("9"),subfield4)
                node={}
                if sset.get("0"):
                        uri=gnd2uri(sset.get("0"))
                        if isinstance(uri,str) and uri.startswith("http"):
                            node["sameAs"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,str):
                            node["identifier"]=gnd2uri(sset.get("0"))
                        elif isinstance(uri,list):
                            node["sameAs"]=None
                            node["identifier"]=None
                            for elem in uri:
                                if elem and elem.startswith("http"):
                                    node["sameAs"]=litter(node["sameAs"],elem)
                                else:
                                    node["identifier"]=litter(node["identifier"],elem)
                if sset.get("a"):
                    node["name"]=sset.get("a")
                if sset.get("n"):
                    node["position"]=sset["n"]
                for typ in ["D","d"]:
                    if sset.get(typ):   #http://www.dnb.de/SharedDocs/Downloads/DE/DNB/wir/marc21VereinbarungDatentauschTeil1.pdf?__blob=publicationFile Seite 14
                        node["@type"]="http://schema.org/"
                        if sset.get(typ)=="p":
                            node["@type"]+="Person"
                        elif sset.get(typ)=="b":
                            node["@type"]+="Organization"
                        elif sset.get(typ)=="f":
                            node["@type"]+="Event"
                        elif sset.get(typ)=="u":
                            node["@type"]+="CreativeWork"
                        elif sset.get(typ)=="g":
                            node["@type"]+="Place"
                        else:
                            node.pop("@type")
                            
                if node:
                    data.append(node)
        if data:
            return  ArrayOrSingleValue(data)
        
        
def deathDate(jline,key,entity):
    return marc_dates(jline.get(key),"deathDate")

def birthDate(jline,key,entity):
    return marc_dates(jline.get(key),"birthDate")

def marc_dates(record,event):
    data=None
    subset=None 
    recset={}
    if record:
        for indicator_level in record:
            for subfield in indicator_level:
                sset={}
                for sf_elem in indicator_level.get(subfield):
                    for k,v in sf_elem.items():
                        if k=="a" or k=="9":
                            sset[k]=v
                if isinstance(sset.get("9"),str):
                    recset[sset['9']]=sset.get("a")
                elif isinstance(sset.get("9"),list):
                    for elem in sset.get("9"):
                        if elem.startswith("4:dat"):
                            recset[elem]=sset.get("a")
    #eprint(recset)
    if recset.get("4:datx"):
        return dateToEvent(recset["4:datx"],event)
    elif recset.get("4:datl"):
        return dateToEvent(recset["4:datl"],event)
    else:
        return None

def getparent(jline,key,entity):
    data=None
    for i in jline[key[0][0:3]][0]:
        sset={}
        for j in jline[key[0][0:3]][0][i]:
            for k,v in dict(j).items():
                sset[k]=v
            conti=False
            if "9" in sset:
                if sset["9"]=='4:adue':
                    conti=True
            if conti and "0" in sset:
                data=litter(data,gnd2uri(sset["0"]))
    if data:
        return data

def honorificSuffix(jline,key,entity):
    data=None
    if key[0][:3] in jline:
        for i in jline.get(key[0][0:3])[0]:
            sset={}
            for j in jline.get(key[0][0:3])[0][i]:
                for k,v in dict(j).items():
                    sset[k]=v
                conti=False
                if "9" in sset:
                    if sset["9"]=='4:adel' or sset["9"]=='4:akad':
                            conti=True
                if conti and "a" in sset:
                    data=litter(data,sset["a"])
    if data:
        return data

    
def hasOccupation(jline,key,entity):
    data=[]
    if key[:3] in jline:
        for i in jline[key[:3]]:
            conti=False
            job=None
            sset={}
            for k,v in i.items():               # v = [{'0': ['(DE-576)210258373', '(DE-588)4219681-4']}, {'a': 'Romanist'}, {'9': '4:berc'}, {'w': 'r'}, {'i': 'Charakteristischer Beruf'}]
                for w in v:                     # w = {'0': ['(DE-576)210258373', '(DE-588)4219681-4']}
                    for c,y in dict(w).items(): # c =0 y = ['(DE-576)210258373', '(DE-588)4219681-4']
                        sset[c]=y
            if "9" in sset:                     #sset = {'a': 'Romanist', 'w': 'r', '0': ['(DE-576)210258373', '(DE-588)4219681-4'], 'i': 'Charakteristischer Beruf', '9': '4:berc'}
                if sset["9"]=='4:berc' or sset["9"]=='4:beru' or sset['9']=='4:akti':
                        conti=True
            if conti:
                if key[-1] in sset:
                    if isinstance(sset[key[-1]],list):
                        for field in sset[key[-1]]:
                            if field[1:7] in isil2sameAs:
                                data.append(gnd2uri(field))
    if data:
        return ArrayOrSingleValue(data)



def getgeo(arr):
    for k,v in traverse(arr,""):
        if isinstance(v,str):
            if '.' in v:
                return v


            #key : {"longitude":["034..d","034..e"],"latitude":["034..f","034..g"]}
def getGeoCoordinates(record,key,entity):
    ret={}
    for k,v in key.items():
        coord=getgeo(getmarc(record,v,entity))
        if coord:
            ret["@type"]="GeoCoordinates"
            ret[k]=coord.replace("N","").replace("S","-").replace("E","").replace("W","-")
    if ret:
        return ret

def getav(record,key,entity):
    retOffers=list()
    offers=getmarc(record,key[0],entity)
    ppn=getmarc(record,key[1],entity)
    if isinstance(offers,str) and offers in isil2sameAs:
        retOffers.append({
           "@type": "Offer",
           "offeredBy": {
                "@id": "https://data.finc.info/resource/organisation/"+offers,
                "@type": "Library",
                "name": isil2sameAs.get(offers),
                "branchCode": offers
            },
           "availability": "http://data.ub.uni-leipzig.de/item/wachtl/"+offers+":ppn:"+ppn
       })
    elif isinstance(offers,list):
        for offer in offers:
            if offer in isil2sameAs:
                retOffers.append({
                        "@type": "Offer",
                        "offeredBy": {
                            "@id": "https://data.finc.info/resource/organisation/"+offer,
                "@type": "Library",
                "name": isil2sameAs.get(offer),
                "branchCode": offer
            },
           "availability": "http://data.ub.uni-leipzig.de/item/wachtl/"+offer+":ppn:"+ppn
               })
    if len(retOffers)>0:
        return retOffers

def removeNone(obj):
    if isinstance(obj, (list, tuple, set)):
        return type(obj)(removeNone(x) for x in obj if x is not None)
    elif isinstance(obj, dict):
        return type(obj)((removeNone(k), removeNone(v))
            for k, v in obj.items() if k is not None and v is not None)
    else:
        return obj

def removeEmpty(obj):
    if isinstance(obj,dict):
        toDelete=[]
        for k,v in obj.items():
            if v:
                v = ArrayOrSingleValue(removeEmpty(v))
            else:
                toDelete.append(k)
        for key in toDelete:
            obj.pop(key)
        return obj
    elif isinstance(obj,str):
        return obj
    elif isinstance(obj,list):
        for elem in obj:
            if elem:
                elem = removeEmpty(elem)
            else:
                del elem
        return obj


#make data more RDF
def check(ldj,entity):
    ldj=removeNone(removeEmpty(ldj))
    for k,v in ldj.items():
        v=ArrayOrSingleValue(v)
    if not ldj:
        return
    if 'genre' in ldj:
        genre=ldj.pop('genre')
        ldj['genre']={}
        ldj['genre']['@type']="Text"
        ldj['genre']["Text"]=genre
    #print(ldj.get("_isil"))
    if ldj.get("identifier") and ldj.get("_isil") and isil2sameAs.get(ldj.get("_isil")):
        if "sameAs" in ldj and isinstance(ldj.get("sameAs"),str):
            ldj["sameAs"]=[ldj.pop("sameAs")]
            ldj["sameAs"].append(uri2url(ldj["_isil"],ldj.pop("identifier")))
        elif "sameAs" in ldj and isinstance(ldj.get("sameAs"),list):
            ldj["sameAs"].append(uri2url(ldj["_isil"],ldj.pop("identifier")))
        else:
            ldj["sameAs"]=uri2url(ldj.get("_isil"),ldj.get("identifier"))
    if isinstance(ldj.get("@id"),str):
        ldj["identifier"]=ldj.get("@id").split("/")[4]
    if 'numberOfPages' in ldj:
        numstring=ldj.pop('numberOfPages')
        try:
            if isinstance(numstring,str):
                if "S." in numstring and isint(numstring.split('S.')[0].strip()):
                    num=int(numstring.split('S.')[0].strip())
                    ldj['numberOfPages']=num
            elif isinstance(numstring,list):
                for number in numstring:
                    if "S." in number and isint(number.split('S.')[0].strip()):
                        num=int(number.split('S.')[0])
                        ldj['numberOfPages']=num
        except IndexError:
            if isint(numstring):
                ldj['numberOfPages']=numstring
            else:
                pass
        except Exception as e:
            with open("error.txt","a") as err:
                print(e,file=err)
    #if entity=="Person":
        #checks=["relatedTo","hasOccupation","birthPlace","deathPlace"]
        #for key in checks:
            #if key in ldj:
                #if isinstance(ldj[key],list):
                    #for pers in ldj[key]:
                        #if "@id" not in pers:
                            #del pers
                #elif isinstance(ldj[key],dict):
                    #if "@id" not in ldj[key]:
                        #ldj.pop(key)
                #elif isinstance(ldj[key],str):
                    #ldj.pop(key)
    for label in ["name","alternativeHeadline","alternateName"]:
        try:
            if label in ldj:
                if isinstance(ldj[label],str):
                    if ldj[label][-2:]==" /":
                        ldj[label]=ldj[label][:-2]
                elif isinstance(ldj[label],list):
                    for n,i in enumerate(ldj[label]):
                        if i[-2:]==" /":
                            ldj[label][n]=i[:-2]
                    if label=="name":
                        name=" ".join(ldj[label])
                        ldj[label]=name
        except:
            eprint(ldj,label)
    if "publisherImprint" in ldj:
        if not isinstance(ldj["@context"],list) and isinstance(ldj["@context"],str):
            ldj["@context"]=list([ldj.pop("@context")])
        ldj["@context"].append(URIRef(u'http://bib.schema.org/'))
    if "isbn" in ldj:
        ldj["@type"]=URIRef(u'http://schema.org/Book')
    if "issn" in ldj:
        ldj["@type"]=URIRef(u'http://schema.org/CreativeWorkSeries')
    if "pub_name" in ldj or "pub_place" in ldj:
        ldj["publisher"]={}
        if "pub_name" in ldj:
            ldj["publisher"]["name"]=ldj.pop("pub_name")
            ldj["publisher"]["@type"]="Organization"
        if "pub_place" in ldj:
            ldj["publisher"]["location"]={"name":ldj.pop("pub_place"),
                                          "type":"Place"}
            if ldj["publisher"]["location"]["name"][-1] in [".",",",";",":"]:
                ldj["publisher"]["location"]["name"]=ldj["publisher"]["location"]["name"][:-1].strip()
        for value in ["name","location"]:        # LOD-JIRA Ticket #105
            if ldj.get("publisher") and ldj.get("publisher").get(value) and isinstance(ldj.get("publisher").get(value),str)and ldj.get("publisher").get(value)[-1] in [",",":",";"]:
                ldj["publisher"][value]=ldj.get("publisher").get(value)[:-1].strip()
    if "sameAs" in ldj:
        ldj["sameAs"]=removeNone(cleanup_sameAs(ldj.pop("sameAs")))
            
    return ldj

def cleanup_sameAs(sameAs):
    if isinstance(sameAs,list):
        for n,elem in enumerate(sameAs):
            sameAs[n]=cleanup_sameAs(elem)
    elif isinstance(sameAs,str):
        if not sameAs.strip().startswith("http"):
            return None
    return sameAs
        

map_entities={
        "p":"persons",      #Personen, individualisiert
        "n":"persons",      #Personen, namen, nicht individualisiert
        "s":"tags",        #Schlagwörter/Berufe
        "b":"orga",         #Organisationen
        "g":"geo",          #Geographika
        "u":"works",     #Werktiteldaten
        "f":"events"
}

def getentity(record):
    zerosevenninedotb=getmarc(record,"079..b",None)
    if zerosevenninedotb in map_entities:
        return map_entities[zerosevenninedotb]
    elif not zerosevenninedotb:
        return "resources"  # Titeldaten ;)
    else:
        return

def getdateModified(record,key,entity):
    date=getmarc(record,key,entity)
    newdate=""
    if date:
        for i in range(0,13,2):
            if isint(date[i:i+2]):
                newdate+=date[i:i+2]
            else:
                newdate+="00"
            if i in (2,4):
                newdate+="-"
            elif i==6:
                newdate+="T"
            elif i in (8,10):
                newdate+=":"
            elif i==12:
                newdate+="Z"
        return newdate

entities = {
   "resources":{   # mapping is 1:1 like works
        "@type"                     :"CreativeWork",
        "@context"                  :"http://schema.org",
        "@id"                       :get_or_generate_id,
        "identifier"                :{getmarcid:["980..a","001"]},
        "offers"                    :{getav:["852..a","980..a"]},
        "_isil"                     :{getisil:["003","852..a","924..b"]},
        "dateModified"              :{getdateModified:"005"},
        "sameAs"                    :{getmarc:["024..a","670..u"]},
        "name"                      :{getmarc:["245..a","245..b"]},
        "nameShort"                 :{getmarc:"245..a"},
        "nameSub"                   :{getmarc:"245..b"},
        "alternativeHeadline"       :{getmarc:["245..c"]},
        "alternateName"             :{getmarc:["240..a","240..p","246..a","246..b","245..p","249..a","249..b","730..a","730..p","740..a","740..p","920..t"]},
        "author"                    :{get_subfields:["100","110"]},
        "contributor"               :{get_subfields:["700","710"]},
        "pub_name"                  :{getmarc:["260..b","264..b"]},
        "pub_place"                 :{getmarc:["260..a","264..a"]},
        "datePublished"             :{getmarc:["130..f","260..c","264..c","362..a"]},
        "Thesis"                    :{getmarc:["502..a","502..b","502..c","502..d"]},
        "issn"                      :{getmarc:["022..a","022..y","022..z","029..a","490..x","730..x","773..x","776..x","780..x","785..x","800..x","810..x","811..x","830..x"]},
        "isbn"                      :{getmarc:["020..a","022..a","022..z","776..z","780..z","785..z"]},
        "genre"                     :{getmarc:"655..a"},
        "hasPart"                   :{getmarc:"773..g"},
        "isPartOf"                  :{getmarc:["773..t","773..s","773..a"]},
        "license"                   :{getmarc:"540..a"},
        "inLanguage"                :{getmarc:["377..a","041..a","041..d","130..l","730..l"]},
        "numberOfPages"             :{getmarc:["300..a","300..b","300..c","300..d","300..e","300..f","300..g"]},
        "pageStart"                 :{getmarc:"773..q"},
        "issueNumber"               :{getmarc:"773..l"},
        "volumeNumer"               :{getmarc:"773..v"},
        "locationCreated"           :{get_subfield_if_4:"551^4:orth"},
        "relatedTo"                 :{relatedTo:"500..0"},
        "about"                     :{handle_about:["936","084","083","082","655"]},
        "description"               :{getmarc:"520..a"},
        "mentions"                  :{get_subfield:"689"},
        "relatedEvent"              :{get_subfield:"711"}
        },
    "works":{   # mapping is 1:1 like resources
        "@type"             :"CreativeWork",
        "@context"      :"http://schema.org",
        "@id"           :get_or_generate_id,
        "identifier"    :{getmarc:"001"},
        "_isil"         :{getisil:"003"},
        "dateModified"   :{getdateModified:"005"},
        "sameAs"        :{getmarc:["024..a","670..u"]},
        "name"              :{getmarc:["130..a","130..p"]},
        "alternativeHeadline"      :{getmarc:["245..c"]},
        "alternateName"     :{getmarc:["240..a","240..p","246..a","246..b","245..p","249..a","249..b","730..a","730..p","740..a","740..p","920..t"]},
        "author"            :{get_subfield:"100"},
        "contributor"       :{get_subfield:"700"},
        "pub_name"          :{getmarc:["260..b","264..b"]},
        "pub_place"         :{getmarc:["260..a","264..a"]},
        "datePublished"     :{getmarc:["130..f","260..c","264..c","362..a"]},
        "Thesis"            :{getmarc:["502..a","502..b","502..c","502..d"]},
        "issn"              :{getmarc:["022..a","022..y","022..z","029..a","490..x","730..x","773..x","776..x","780..x","785..x","800..x","810..x","811..x","830..x"]},
        "isbn"              :{getmarc:["020..a","022..a","022..z","776..z","780..z","785..z"]},
        "genre"             :{getmarc:"655..a"},
        "hasPart"           :{getmarc:"773..g"},
        "isPartOf"          :{getmarc:["773..t","773..s","773..a"]},
        "license"           :{getmarc:"540..a"},
        "inLanguage"        :{getmarc:["377..a","041..a","041..d","130..l","730..l"]},
        "numberOfPages"     :{getmarc:["300..a","300..b","300..c","300..d","300..e","300..f","300..g"]},
        "pageStart"         :{getmarc:"773..q"},
        "issueNumber"       :{getmarc:"773..l"},
        "volumeNumer"       :{getmarc:"773..v"},
        "locationCreated"   :{get_subfield_if_4:"551^4:orth"},
        "relatedTo"         :{relatedTo:"500..0"}
        },
    "persons": {
        "@type"         :"Person",
        "@context"      :"http://schema.org",
        "@id"           :get_or_generate_id,
        "identifier"    :{getmarc:"001"},
        "_isil"         :{getisil:"003"},
        "dateModified"   :{getdateModified:"005"},
        "sameAs"        :{getmarc:["024..a","670..u"]},
        
        "name"          :{getmarc:"100..a"},
        "gender"        :{handlesex:"375..a"},
        "alternateName" :{getmarc:["400..a","400..c"]},
        "relatedTo"     :{relatedTo:"500..0"},
        "hasOccupation" :{get_subfield:"550"},
        "birthPlace"    :{get_subfield_if_4:"551^4:ortg"},
        "deathPlace"    :{get_subfield_if_4:"551^4:orts"},
        "honorificSuffix" :{honorificSuffix:["550..0","550..i","550..a","550..9"]},
        "birthDate"     :{birthDate:"548"},
        "deathDate"     :{deathDate:"548"},
        "workLocation"  :{get_subfield_if_4:"551^4:ortw"},
        "about"                     :{handle_about:["936","084","083","082","655"]},
    },
    "orga": {
        "@type"             :"Organization",
        "@context"          :"http://schema.org",
        "@id"               :get_or_generate_id,
        "identifier"        :{getmarc:"001"},
        "_isil"             :{getisil:"003"},
        "dateModified"       :{getdateModified:"005"},
        "sameAs"            :{getmarc:["024..a","670..u"]},
        
        "name"              :{getmarc:"110..a"},
        "alternateName"     :{getmarc:"410..a+b"},
        
        "additionalType"    :{get_subfield_if_4:"550^4:obin"},
        "parentOrganization":{get_subfield_if_4:"551^4:adue"},
        "location"          :{get_subfield_if_4:"551^4:orta"},
        "fromLocation"      :{get_subfield_if_4:"551^4:geoa"},
        "areaServed"        :{get_subfield_if_4:"551^4:geow"},
        "about"                     :{handle_about:["936","084","083","082","655"]},
        },
    "geo": {
        "@type"             :"Place",
        "@context"          :"http://schema.org",
        "@id"               :get_or_generate_id,
        "identifier"        :{getmarc:"001"},
        "_isil"             :{getisil:"003"},
        "dateModified"       :{getdateModified:"005"},
        "sameAs"            :{getmarc:["024..a","670..u"]},
        
        "name"              :{getmarc:"151..a"},
        "alternateName"     :{getmarc:"451..a"},
        "description"       :{get_subfield:"551"},
        "geo"               :{getGeoCoordinates:{"longitude":["034..d","034..e"],"latitude":["034..f","034..g"]}},
        "adressRegion"      :{getmarc:"043..c"},
        "about"             :{handle_about:["936","084","083","082","655"]},
        },
    "tags":{                   #generisches Mapping für Schlagwörter
        "@type"             :"Thing",
        "@context"          :"http://schema.org",
        "@id"               :get_or_generate_id,
        "identifier"        :{getmarc:"001"},
        "_isil"             :{getisil:"003"},
        "dateModified"       :{getdateModified:"005"},
        "sameAs"            :{getmarc:["024..a","670..u"]},
        "name"              :{getmarc:"150..a"},
        "alternateName"     :{getmarc:"450..a+x"},
        "description"       :{getmarc:"679..a"},
        "additionalType"    :{get_subfield:"550"},
        "location"          :{get_subfield_if_4:"551^4:orta"},
        "fromLocation"      :{get_subfield_if_4:"551^4:geoa"},
        "areaServed"        :{get_subfield_if_4:"551^4:geow"},
        "contentLocation"   :{get_subfield_if_4:"551^4:punk"},
        "participant"       :{get_subfield_if_4:"551^4:bete"},
        "relatedTo"         :{get_subfield_if_4:"551^4:vbal"},
        "about"             :{handle_about:["936","084","083","082","655"]},
        },
    
    "events": {
        "@type"         :"Event",
        "@context"      :"http://schema.org",
        "@id"           :get_or_generate_id,
        "identifier"    :{getmarc:"001"},
        "_isil"         :{getisil:"003"},
        "dateModified"  :{getdateModified:"005"},
        "sameAs"        :{getmarc:["024..a","670..u"]},
        
        "name"          :{getmarc:["111..a"]},
        "alternateName" :{getmarc:["411..a"]},
        "location"      :{get_subfield_if_4:"551^4:ortv"},
        "startDate"     :{birthDate:"548"},
        "endDate"       :{deathDate:"548"},
        "adressRegion"  :{getmarc:"043..c"},
        "about"         :{handle_about:["936","084","083","082","655"]},
    },
}

def traverse(dict_or_list, path):
    iterator=None
    if isinstance(dict_or_list, dict):
        iterator = dict_or_list.items()
    elif isinstance(dict_or_list, list):
        iterator = enumerate(dict_or_list)
    elif isinstance(dict_or_list,str):
        strarr=[]
        strarr.append(dict_or_list)
        iterator=enumerate(strarr)
    else:
        return
    if iterator:
        for k, v in iterator:
            yield path + str([k]), v
            if isinstance(v, (dict, list)):
                for k, v in traverse(v, path + str([k])):
                    yield k, v


def get_source_include_str():
    items=set()
    items.add("079")
    for k,v in traverse(entities,""):
        #eprint(k,v)
        if isinstance(v,str) and isint(v[:3]) and v not in items:
                items.add(v[:3])
    _source=",".join(items)
    #eprint(_source)
    return _source
    
def process_field(record,value,entity):
    ret=[]
    if isinstance(value,dict):
        for function,parameter in value.items():
            ret.append(function(record,parameter,entity))
    elif isinstance(value,str):
        return value
    elif isinstance(value,list):
        for elem in value:
            ret.append(ArrayOrSingleValue(process_field(record,elem,entity)))
    elif callable(value):
        return ArrayOrSingleValue(value(record,entity))
    if ret:
        return ArrayOrSingleValue(ret)


#processing a single line of json without whitespace 
def process_line(jline,host,port,index,type):
    entity=getentity(jline)
    if entity:
        mapline={}
        mapline["@type"]=[URIRef(u'http://schema.org/'+entity)]
        mapline["@context"]=[URIRef(u'http://schema.org')]
        for key,val in entities[entity].items():
            value=process_field(jline,val,entity)
            if value:
                if "related" in key and  isinstance(value,dict) and "_key" in value:
                    dictkey=value.pop("_key")
                    mapline[dictkey]=litter(mapline[dictkey],value)
                elif "related" in key and isinstance(value,list):
                    for elem in value:
                        if "_key" in elem:
                            relation=elem.pop("_key")
                            dictkey=relation
                            mapline[dictkey]=litter(mapline[dictkey],elem)
                else:
                    mapline[key]=value
        mapline=check(mapline,entity)
        if host and port and index and type:
            mapline["url"]="http://"+host+":"+str(port)+"/"+index+"/"+type+"/"+getmarc(jline,"001",None)+"?pretty"
        return {entity:mapline}
    
def output(entity,mapline,outstream):
    if outstream:
        outstream[entity].write(json.dumps(mapline,indent=None)+"\n")
    else:
        sys.stdout.write(json.dumps(mapline,indent=None)+"\n")
        sys.stdout.flush()


def setupoutput(prefix):
    if prefix:
        if not os.path.isdir(prefix):
            os.mkdir(prefix)
        if not prefix[-1]=="/":
            prefix+="/"
    else:
        prefix=""
    for entity in entities:
        if not os.path.isdir(prefix+entity):
            os.mkdir(prefix+entity)

def init_mp(h,p,pr):
    global host
    global port
    global outstream
    global filepaths
    global prefix
    if not pr:
        prefix = ""
    elif pr[-1]!="/":
        prefix=pr+"/"
    else:
        prefix=pr
    port = p
    host = h
    outstream={}
    filepaths=[]

def worker(ldj):
    #out={}
    #for entity in entities:
    #    out[entity]=open(prefix+entity+"/"+str(current_process().name)+"-records.ldj","a")
    try:
        if isinstance(ldj,list):    # list of records
            for source_record in ldj:
                target_record=process_line(source_record.pop("_source"),host,port,source_record.pop("_index"),source_record.pop("_type"))
                if target_record:
                    for entity in target_record:
                        with open(prefix+entity+"/"+str(current_process().name)+"-records.ldj","a") as out:
                            print(json.dumps(target_record[entity],indent=None),file=out)
        elif isinstance(ldj,dict): # single record
            target_record=process_line(ldj.pop("_source"),host,port,ldj.pop("_index"),ldj.pop("_type"))
            if target_record:
                for entity in target_record:
                    with open(prefix+entity+"/"+str(current_process().name)+"-records.ldj","a") as out:
                        print(json.dumps(target_record[entity],indent=None),file=out)
    except Exception as e:
        with open("errors.txt",'a') as f:
            traceback.print_exc(file=f)
        
        
if __name__ == "__main__":
    #argstuff
    parser=argparse.ArgumentParser(description='Entitysplitting/Recognition of MARC-Records')
    parser.add_argument('-host',type=str,help='hostname or IP-Address of the ElasticSearch-node to use. If None we try to read ldj from stdin.')
    parser.add_argument('-port',type=int,default=9200,help='Port of the ElasticSearch-node to use, default is 9200.')
    parser.add_argument('-type',type=str,help='ElasticSearch Type to use')
    parser.add_argument('-index',type=str,help='ElasticSearch Index to use')
    parser.add_argument('-id',type=str,help='map single document, given by id')
    parser.add_argument('-help',action="store_true",help="print this help")
    parser.add_argument('-prefix',type=str,default="ldj/",help='Prefix to use for output data')
    parser.add_argument('-debug',action="store_true",help='Dump processed Records to stdout (mostly used for debug-purposes)')
    parser.add_argument('-server',type=str,help="use http://host:port/index/type/id?pretty syntax. overwrites host/port/index/id/pretty")
    parser.add_argument('-pretty',action="store_true",default=False,help="output tabbed json")
    parser.add_argument('-w',type=int,default=8,help="how many processes to use")
    parser.add_argument('-idfile',type=str,help="path to a file with IDs to process")
    parser.add_argument('-query',type=str,default={},help='prefilter the data based on an elasticsearch-query')
    parser.add_argument('-generate_ids',action="store_true",help="switch on if you wan't to generate IDs instead of looking them up. usefull for first-time ingest or debug purposes")
    parser.add_argument('-lookup_host',type=str,help="Target or Lookup Elasticsearch-host, where the result data is going to be ingested to. Only used to lookup IDs (PPN) e.g. http://192.168.0.4:9200")
    args=parser.parse_args()
    if args.server:
        slashsplit=args.server.split("/")
        args.host=slashsplit[2].rsplit(":")[0]
        if isint(args.server.split(":")[2].rsplit("/")[0]):
            args.port=args.server.split(":")[2].split("/")[0]
        args.index=args.server.split("/")[3]
        if len(slashsplit)>4:
            args.type=slashsplit[4]
        if len(slashsplit)>5:
            if "?pretty" in args.server:
                args.pretty=True
                args.id=slashsplit[5].rsplit("?")[0]
            else:
                args.id=slashsplit[5]
    if args.server or ( args.host and args.port ):
        es=elasticsearch.Elasticsearch([{"host":args.host}],port=args.port)
    if args.pretty:
        tabbing=4
    else:
        tabbing=None
    if args.generate_ids:
        generate=True
    if not args.lookup_host and not args.generate_ids and args.server:
        lookup_host=args.host
        lookup_port=args.port
    if args.lookup_host and not args.generate_ids:
        lookup_slashsplit=args.lookup_host.split("/")
        lookup_host=lookup_slashsplit[2].rsplit(":")[0]
        if isint(args.lookup_host.split(":")[2].rsplit("/")[0]):
            lookup_port=args.lookup_host.split(":")[2].split("/")[0]
    else:
        eprint("Please use -host and -port or -server or -lookup_host for searching ids. Or us -generate_ids if you want to produce fresh data")
        args.generate_ids=False
    if not args.generate_ids:
        eprint(lookup_host,lookup_port)
        lookup_es=elasticsearch.Elasticsearch([{"host":lookup_host}],port=lookup_port)
    if args.help:
        parser.print_help(sys.stderr)
        exit()        
    elif args.host and args.index and args.type and args.id:
        json_record=None
        source=get_source_include_str()
        json_record=es.get_source(index=args.index,doc_type=args.type,id=args.id,_source=source)
        if json_record:
            print(json.dumps(process_line(json_record,args.host,args.port,args.index,args.type),indent=tabbing))
    elif args.host and args.index and args.type and args.idfile:
        setupoutput(args.prefix)
        pool = Pool(args.w,initializer=init_mp,initargs=(args.host,args.port,args.prefix))
        for ldj in esidfilegenerator(host=args.host,
                       port=args.port,
                       index=args.index,
                       type=args.type,
                       source=get_source_include_str(),
                       body=args.query,
                       idfile=args.idfile
                        ):
            pool.apply_async(worker,args=(ldj,))
        pool.close()
        pool.join()
    elif args.host and args.index and args.type and args.debug:
        init_mp(args.host,args.port,None)
        for ldj in esgenerator(host=args.host,
                       port=args.port,
                       index=args.index,
                       type=args.type,
                       source=get_source_include_str(),
                       headless=True,
                       body=args.query
                        ): 
            record = process_line(ldj,args.host,args.port,args.index,args.type)
            if record:
                for k in record:
                    print(json.dumps(record[k],indent=None))
    elif args.host and args.index and args.type : #if inf not set, than try elasticsearch
        setupoutput(args.prefix)
        pool = Pool(args.w,initializer=init_mp,initargs=(args.host,args.port,args.prefix))
        for ldj in esfatgenerator(host=args.host,
                       port=args.port,
                       index=args.index,
                       type=args.type,
                       source=get_source_include_str(),
                       body=args.query
                        ):
            pool.apply_async(worker,args=(ldj,))
        pool.close()
        pool.join()
    else: #oh noes, no elasticsearch input-setup. then we'll use stdin
        eprint("No host/port/index specified, trying stdin\n")
        init_mp("localhost","DEBUG","DEBUG")
        with io.TextIOWrapper(sys.stdin.buffer, encoding='utf-8') as input_stream:
            for line in input_stream:
                ret=process_line(json.loads(line),"localhost",9200,"data","mrc")
                if isinstance(ret,dict):
                    for k,v in ret.items():
                        print(json.dumps(v,indent=tabbing))
                        
    #cleanup
    
