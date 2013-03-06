# -*- coding: utf-8 -*-

# MegaDown beta.0.2

# Script basado en la información publicada en el blog:
# http://julien-marchand.fr/blog/using-the-mega-api-how-to-download-a-public-file-or-a-file-you-know-the-key-without-logging-in/
# y en el proyecto https://github.com/CyberjujuM/MegaFS

# Adptaciones e implementación como gestor de descarga realizadas por TheMonti


from progressbar import  Bar, ETA, \
     FileTransferSpeed,  Percentage, \
    ProgressBar,  Timer
from megacrypto import *

import os
import sys
import ConfigParser
import signal
import sys
from functools import partial
from itertools import count, izip
from multiprocessing.dummy import Pool # use threads
from urllib2 import HTTPError, Request, urlopen
import time
import re


class Mega():
  def __init__(self):
    signal.signal(signal.SIGINT, self.megadown_signal_handler)
    # print sys.argv[1:]
    self.threaduid = 0
    self.app = 'MegaDown'
    self.version = 'beta0.2'
    self.title = 'Gestor de descargas de mega.co.nz'
    self.conexiones=10

    # config = ConfigParser.ConfigParser()
    # config.readfp(open('megadown.cfg'))
    # self.app = config.get('MEGADOWN','app')
    # self.version = config.get('MEGADOWN','version')
    # self.title = config.get('MEGADOWN','title'))
    # self.conexiones = int(config.get('mega.co.nz','conexiones'))
    self.megadown_print("%s %s - %s\n"%(self.app,self.version,self.title))
    
    files=raw_input("Introduzca link de mega:")
    if files.find('mega')>-1:
      for url in files.split(','):
        path = self.megadown_parse_url(url).split('!')
        file_id = path[0]
        file_key = path[1]
        self.megadown_getfile(file_id, file_key)
  
  def megadown_print(self,mensaje):
    print mensaje

  def megadown_parse_url(self, url):
        #parse file id and key from url
        if ('!' in url):
            match = re.findall(r'/#!(.*)', url)
            path = match[0]
            return path
        else:
            raise RequestError('Url key missing')
  def megadown_getfile(self,file_id, file_key):
    key = base64_to_a32(file_key)
    k = (key[0] ^ key[4], key[1] ^ key[5], key[2] ^ key[6], key[3] ^ key[7])
    iv = key[4:6] + (0, 0)
    meta_mac = key[6:8]
   
    self.megadown_print("\n\nObteniendo acceso al link de mega.co.nz: %s"%(file_id))
    
    file = api_req({'a': 'g', 'g': 1, 'p': file_id})
    dl_url = file['g']
    size = file['s']
    attributes = base64urldecode(file['at']) 
    attributes = dec_attr(attributes, k)
    
    self.megadown_print ("Fichero localizado: %s [%s]" % (attributes['n'],  self.megadown_GetHumanReadable(size)))
   
    decryptor = AES.new(a32_to_str(k), AES.MODE_CTR, counter = Counter.new(128, initial_value = ((iv[0] << 32) + iv[1]) << 64))
   
    file_mac = [0, 0, 0, 0]

    url=dl_url
    filename = attributes['n']
    pool = Pool(self.conexiones) # define number of concurrent connections
    
    #--------------------- 
    # PROGRESSBAR
    #---------------------   
    widgets = ['Descarga: ', Percentage(), ' ', Bar(marker='#'),
                 ' ', ETA(), ' ', FileTransferSpeed()]
    pbar = ProgressBar(widgets=widgets, maxval=size).start()
    #--------------------- 
    
    listchunks=sorted(get_chunks(file['s']).items())
    # print listchunks
    ranges=listchunks
    with open(filename, 'wb') as file:
        for content in pool.imap(partial(self.download_chunk, url), ranges):
            if not content:
                print "Error EOF"
                break # error or EOF
            content=decryptor.decrypt(content)
            file.write(content)
            pbar.update(os.path.getsize(filename))
            # if len(s) != size:
            #     break  # EOF (servers with no Range support end up here)
    #--------------------- 
    pbar.finish()
    #--------------------- 

  def download_chunk(self,url,  byterange):
      self.threaduid += 1

      chunk_start,chunk_size=byterange
      descargando='bytes=%d-%d' % (chunk_start,chunk_start+chunk_size-1)
      # print "Hilo ",uid,":",descargando
      req = Request(url, headers=dict(Range='bytes=%d-%d' % (chunk_start,chunk_start+chunk_size-1)))
      try:
          chunk = urlopen(req).read()
          return chunk
      except HTTPError as e:
          # print "Hilo terminado - KO DESCARGA"
          return b''  if e.code == 416 else None  # treat range error as EOF
      except EnvironmentError:
          # print "Hilo terminado - KO DESCARGA"
          return None
  def megadown_GetHumanReadable(self,size,precision=2):
    suffixes=['B','KB','MB','GB','TB']
    suffixIndex = 0
    while size > 1024:
        suffixIndex += 1 #increment the index of the suffix
        size = size/1024.0 #apply the division
    return "%.*f %s" % (precision,size,suffixes[suffixIndex])


  def megadown_signal_handler(self,signal, frame):
    self.megadown_print('\nLa descarga ha sido abortada.\n\nGracias por utilizar megadown.')
    sys.exit(0)


if __name__ == '__main__':
  
  # t0 = time.time()
  mega=Mega()
  # print time.time()-t0
  mega.megadown_print('\n\nGracias por utilizar %s.\n\n' %(mega.app))

