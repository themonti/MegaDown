# -*- coding: utf-8 -*-
#!/usr/bin/python
# Filename: megadown.py


# MegaDown beta.0.3

# Script basado en la información publicada en el blog:
# http://julien-marchand.fr/blog/using-the-mega-api-how-to-download-a-public-file-or-a-file-you-know-the-key-without-logging-in/
# y en el proyecto https://github.com/CyberjujuM/MegaFS

# Adptaciones e implementación como gestor de descarga realizadas por TheMonti


from progressbar import  Bar, ETA, \
     FileTransferSpeed,  Percentage, \
    ProgressBar,  Timer


import os
import sys
import ConfigParser
import signal
import sys
import time
import re
from functools import partial
from itertools import count, izip
from multiprocessing.dummy import Pool # use threads
from urllib2 import HTTPError, Request, urlopen
from Crypto.Cipher import AES
from Crypto.PublicKey import RSA
from Crypto.Util import Counter
import base64
import binascii
import json
import struct
import random
import shutil


sid = ''
seqno = random.randint(0, 0xFFFFFFFF)

def base64urldecode(data):
  data += '=='[(2 - len(data) * 3) % 4:]
  for search, replace in (('-', '+'), ('_', '/'), (',', '')):
    data = data.replace(search, replace)
  return base64.b64decode(data)
 
def base64urlencode(data):
  data = base64.b64encode(data)
  for search, replace in (('+', '-'), ('/', '_'), ('=', '')):
    data = data.replace(search, replace)
  return data
 
def a32_to_str(a):
  return struct.pack('>%dI' % len(a), *a)
 
def a32_to_base64(a):
  return base64urlencode(a32_to_str(a))
 
def str_to_a32(b):
  if len(b) % 4: # Add padding, we need a string with a length multiple of 4
    b += '\0' * (4 - len(b) % 4)
  return struct.unpack('>%dI' % (len(b) / 4), b)
 
def base64_to_a32(s):
  return str_to_a32(base64urldecode(s))
 
def aes_cbc_encrypt(data, key):
  encryptor = AES.new(key, AES.MODE_CBC, '\0' * 16)
  return encryptor.encrypt(data)
 
def aes_cbc_decrypt(data, key):
  decryptor = AES.new(key, AES.MODE_CBC, '\0' * 16)
  return decryptor.decrypt(data)
 
def aes_cbc_encrypt_a32(data, key):
  return str_to_a32(aes_cbc_encrypt(a32_to_str(data), a32_to_str(key)))
 
def aes_cbc_decrypt_a32(data, key):
  return str_to_a32(aes_cbc_decrypt(a32_to_str(data), a32_to_str(key)))
 
def stringhash(s, aeskey):
  s32 = str_to_a32(s)
  h32 = [0, 0, 0, 0]
  for i in xrange(len(s32)):
    h32[i % 4] ^= s32[i]
  for _ in xrange(0x4000):
    h32 = aes_cbc_encrypt_a32(h32, aeskey)
  return a32_to_base64((h32[0], h32[2]))
 
def prepare_key(a):
  pkey = [0x93C467E3, 0x7DB0C7A4, 0xD1BE3F81, 0x0152CB56]
  for _ in xrange(0x10000):
    for j in xrange(0, len(a), 4):
      key = [0, 0, 0, 0]
      for i in xrange(4):
        if i + j < len(a):
          key[i] = a[i + j]
      pkey = aes_cbc_encrypt_a32(pkey, key)
  return pkey
 
def encrypt_key(a, key):
  return sum((aes_cbc_encrypt_a32(a[i:i+4], key) for i in xrange(0, len(a), 4)), ())
 
def decrypt_key(a, key):
  return sum((aes_cbc_decrypt_a32(a[i:i+4], key) for i in xrange(0, len(a), 4)), ())
 
def mpi2int(s):
  return int(binascii.hexlify(s[2:]), 16)
 
def api_req(req):
  global seqno
  url = 'https://g.api.mega.co.nz/cs?id=%d%s' % (seqno, '&sid=%s' % sid if sid else '')
  seqno += 1
  return json.loads(post(url, json.dumps([req])))[0]
 
def post(url, data):
  return urlopen(url, data).read()
 
def enc_attr(attr, key):
  attr = 'MEGA' + json.dumps(attr)
  if len(attr) % 16:
    attr += '\0' * (16 - len(attr) % 16)
  return aes_cbc_encrypt(attr, a32_to_str(key))
 
def dec_attr(attr, key):
  attr = aes_cbc_decrypt(attr, a32_to_str(key)).rstrip('\0')
  return json.loads(attr[4:]) if attr[:6] == 'MEGA{"' else False
 
def get_chunks(size):
  chunks = {}
  p = pp = 0
  i = 1
 
  while i <= 8 and p < size - i * 0x20000:
    chunks[p] = i * 0x20000;
    pp = p
    p += chunks[p]
    i += 1
 
  while p < size:
    chunks[p] = 0x100000;
    pp = p
    p += chunks[p]
 
  chunks[pp] = size - pp
  if not chunks[pp]:
    del chunks[pp]
  return chunks

class Mega():
  def __init__(self):
    signal.signal(signal.SIGINT, self.megadown_signal_handler)
    # print sys.argv[1:]
    self.threaduid = 0
    self.app = 'MegaDown'
    self.version = 'beta0.3'
    self.title = 'Gestor de descargas de mega.co.nz'
    self.conexiones=10
    self.dirdescarga=os.path.abspath("./")


    # config = ConfigParser.ConfigParser()
    # config.readfp(open('megadown.cfg'))
    # self.app = config.get('MEGADOWN','app')
    # self.version = config.get('MEGADOWN','version')
    # self.title = config.get('MEGADOWN','title'))
    # self.conexiones = int(config.get('mega.co.nz','conexiones'))

    self.megadown_print("%s %s - %s\n"%(self.app,self.version,self.title))

    if len(sys.argv) < 2:
      self.megadown_solicitar_link()
    else:
      if sys.argv[1].startswith('--'):
        option = sys.argv[1][2:]
        # print "option",option
        # fetch sys.argv[1] but without the first two characters
        if option == 'conexiones' :
          self.conexiones = int(sys.argv[2])
          self.megadown_solicitar_link()
        elif option == "version":
          print "Version",self.version
        elif option == 'help':
          t="""\
      Este programa permite descargar ficheros desde mega.co.nz.
      Puede utilizar estas opciones:
        --conexiones 10    : Conexiones activas con mega.co.nz. Por defecto [10]
        --path ~/Downloads : Directorio de descarga
        --version    : Presenta la versión de la aplicacion
        --help       : Muestra esta ayuda"""
          self.megadown_print(t)
        else:
          self.megadown_print('Opción desconocida. Use --help para ver opciones disponibles.')
      else:
        self.megadown_print('Opción desconocida. Use --help para ver opciones disponibles.')
      
  def megadown_solicitar_link(self):
    files=raw_input("Introduzca uno o varios link's de mega.co.nz (separados por ,): ")
    # Pruebas:
    # files="https://mega.co.nz/#!MNE0mJDB!dTRxvDzVV0N3_d8iACFuwlnR87ldsHf8fl5xrGk36k0,https://mega.co.nz/#!NBMSGI7T!V03qPTuE7Qqrb2WIDUsPOVh5QsYE1Wun8SVkqEIOJbA"
    while files.find('mega.co.nz')==-1:
      files=raw_input("No se encontraron links de mega.\nIntroduzca uno o varios link's de mega.co.nz (separados por ,) o pulse (CTRL+C) para salir:")
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
    self.megadown_print("Espere por favor...")

    file = api_req({'a': 'g', 'g': 1, 'p': file_id})
    dl_url = file['g']
    size = file['s']
    attributes = base64urldecode(file['at']) 
    attributes = dec_attr(attributes, k)
    
    self.megadown_print ("Fichero encontrado: %s [%s]\n" % (attributes['n'],  self.megadown_GetHumanReadable(size)))
   
    decryptor = AES.new(a32_to_str(k), AES.MODE_CTR, counter = Counter.new(128, initial_value = ((iv[0] << 32) + iv[1]) << 64))
   
    file_mac = [0, 0, 0, 0]

    url=dl_url
    filename = attributes['n']
    pool = Pool(self.conexiones) # define number of concurrent connections
    
    #--------------------- 
    # PROGRESSBAR
    #---------------------   
    widgets = ['Descargando: ', Percentage(), ' ', Bar(marker='#'),
                 ' ', ETA(), ' ', FileTransferSpeed()]
    pbar = ProgressBar(widgets=widgets, maxval=size).start()
    #--------------------- 
    
    listchunks=sorted(get_chunks(file['s']).items())
    # print listchunks
    ranges=listchunks
    lentotal=0
    # with open(filename, 'wb') as file:
    directory="%s/tmp_%s"%(self.dirdescarga,file_id)
    if not os.path.exists(directory):
        os.makedirs(directory)
    for content in pool.imap(partial(self.download_chunk, url, os.path.abspath(directory)), ranges):
        if not content:
            print "Error EOF"
            break # error or EOF
        # content=decryptor.decrypt(content)
        # file.write(content)
        lentotal+=content
        pbar.update(lentotal)
        # if len(s) != size:
        #     break  # EOF (servers with no Range support end up here)
    #--------------------- 
    pbar.finish()
    #--------------------- 
    
    #--------------------- 
    # PROGRESSBAR
    #---------------------   
    widgets = ['Desencriptando: ', Percentage(), ' ', Bar(marker='#'),
                 ' ', ETA()]
    pbar = ProgressBar(widgets=widgets, maxval=size).start()
    #--------------------- 
    
    output=open(attributes['n'],'wb')
    for chunk_start,chunk_size in ranges:
      input_name="%s/%s.chunk"%(os.path.abspath(directory),chunk_start)
      input_tmp=open(input_name,'rb')
      chunk=input_tmp.read()
      chunk=decryptor.decrypt(chunk)
      output.write(chunk)
      input_tmp.close()
      os.remove(input_name)
      pbar.update(os.path.getsize(attributes['n']))
    shutil.rmtree(os.path.abspath(directory))
    output.close()
    #--------------------- 
    pbar.finish()
    #--------------------- 
    
  def download_chunk(self,url, file_id, byterange):
      self.threaduid += 1

      chunk_start,chunk_size=byterange
      descargando='bytes=%d-%d' % (chunk_start,chunk_start+chunk_size-1)
      # print "Hilo ",uid,":",descargando
      output_name="%s/%s.chunk"%(file_id,chunk_start)
      req = Request(url, headers=dict(Range='bytes=%d-%d' % (chunk_start,chunk_start+chunk_size-1)))
      try:
          output=open(output_name,'wb')
          chunk = urlopen(req).read()
          output.write(chunk)
          output.close()
          return chunk_size
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
    self.megadown_print('\nLa descarga ha sido abortada.\n\nGracias por utilizar %s.'%(self.app))
    sys.exit(0)


if __name__ == '__main__':
  
  # t0 = time.time()
  mega=Mega()
  # print time.time()-t0
  mega.megadown_print('\n\nGracias por utilizar %s.\n\n' %(mega.app))

