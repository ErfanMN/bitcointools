from decimal import Decimal
import hashlib
import socket
import binascii
import time

from .base58 import public_key_to_bc_address, hash_160_to_bc_address
from .enumeration import Enumeration
from .util import short_hex, long_hex
import struct
from . import segwit_addr

def parse_CAddress(vds):
  d = {}
  d['nVersion'] = vds.read_int32()
  d['nTime'] = vds.read_uint32()
  d['nServices'] = vds.read_int64()
  d['pchReserved'] = vds.read_bytes(12)
  d['ip'] = socket.inet_ntoa(vds.read_bytes(4))
  d['port'] = socket.htons(vds.read_uint16())
  return d

def deserialize_CAddress(d):
  return d['ip']+":"+str(d['port'])+" (lastseen: %s)"%(time.ctime(d['nTime']),)

def parse_setting(setting, vds):
  if setting[0] == "f":  # flag (boolean) settings
    return str(vds.read_boolean())
  elif setting == "addrIncoming":
    return "" # bitcoin 0.4 purposely breaks addrIncoming setting in encrypted wallets.
  elif setting[0:4] == "addr": # CAddress
    d = parse_CAddress(vds)
    return deserialize_CAddress(d)
  elif setting == "nTransactionFee":
    return vds.read_int64()
  elif setting == "nLimitProcessors":
    return vds.read_int32()
  return 'unknown setting'

def parse_TxIn(vds):
  d = {}
  d['prevout_hash'] = vds.read_bytes(32)
  d['prevout_n'] = vds.read_uint32()
  d['scriptSig'] = vds.read_bytes(vds.read_compact_size())
  d['sequence'] = vds.read_uint32()
  return d

def deserialize_TxIn(d, transaction_index=None, owner_keys=None):
  result = {}
  if d['prevout_hash'] == b"\x00"*32:
    result['coinbase'] = d['scriptSig'].hex()
  else:
    result['txid'] = long_hex(d['prevout_hash'][::-1])
    result['vout'] = d['prevout_n']
  result['sequence']=d['sequence']
  return result

def parse_TxOut(vds):
  d = {}
  d['value'] = vds.read_int64()
  d['scriptPubKey'] = vds.read_bytes(vds.read_compact_size())
  return d

def deserialize_TxOut(d, owner_keys=None, version=b'\x00'):
  result = {}
  result['value'] = Decimal(d['value']) / Decimal(1.0e8)
  pk = extract_public_key(d['scriptPubKey'], version)
  addr_list = []
  if type(pk) is list:
    addr_list = pk
  elif pk:
    addr_list = [pk]
  result['scriptPubKey']={}
  result['scriptPubKey']['addresses'] = addr_list
  return result

def parse_Transaction(vds):
  #For format see transaction serialization
  #in https://bitcoincore.org/en/segwit_wallet_dev/
  d = {}
  flag = 0
  #We need to exclude witness and flag data
  #for txid calculation
  tx_data = b''
  start_data_pos = vds.read_cursor 
  tx_data_pos = vds.read_cursor
  d['version'] = vds.read_int32()
  tx_data += vds.input[tx_data_pos:vds.read_cursor]
  
  tx_data_pos = vds.read_cursor
  n_vin = vds.read_compact_size()
  if (n_vin == 0):
    flag = vds.read_compact_size()
    if (flag != 1):
      raise Exception('Segwit error: expecting 1 got {}'.format(flag))
 
  if (flag):    
    tx_data_pos = vds.read_cursor
    n_vin = vds.read_compact_size()
  
  d['txIn'] = []
  for i in range(n_vin):
    d['txIn'].append(parse_TxIn(vds))
  n_vout = vds.read_compact_size()
  d['txOut'] = []
  for i in range(n_vout):
    d['txOut'].append(parse_TxOut(vds))

  tx_data += vds.input[tx_data_pos:vds.read_cursor]
  
  if (flag):  
    read_witness_data(vds, n_vin)  
  
  tx_data_pos = vds.read_cursor
  d['lockTime'] = vds.read_uint32()
  tx_data += vds.input[tx_data_pos:vds.read_cursor]

  d['__data__'] = tx_data
  d['size'] = vds.read_cursor - start_data_pos 
  return d

def read_witness_data(vds, txin_size):
  for i in range(0, txin_size):
    no_items = vds.read_compact_size()
    for j in range(0, no_items):
      item_size = vds.read_compact_size()
      #Read the witness item
      out = vds.read_bytes(item_size)

def deserialize_Transaction(d, transaction_index=None, owner_keys=None,
                            print_raw_tx=False, version=b'\x00'):
  result = {}
  result['vin'] = []
  result['vout'] = []
  result['size'] = d['size']
  for txIn in d['txIn']:
    result['vin'].append(deserialize_TxIn(txIn, transaction_index)) 
  for (idx,txOut) in enumerate(d['txOut']):
    txout = deserialize_TxOut(txOut, owner_keys, version)
    txout['n'] = idx
    result['vout'].append(txout)
  result['txid'] = binascii.hexlify(hashlib.sha256(hashlib.sha256(d['__data__']).digest()).digest()[::-1])
  result['vsize']=int(round((3*len(d['__data__'])+result['size'])/4.0))
  return result

def parse_MerkleTx(vds):
  d = parse_Transaction(vds)
  d['hashBlock'] = vds.read_bytes(32)
  n_merkleBranch = vds.read_compact_size()
  d['merkleBranch'] = vds.read_bytes(32*n_merkleBranch)
  d['nIndex'] = vds.read_int32()
  return d

def deserialize_MerkleTx(d, transaction_index=None, owner_keys=None):
  tx = deserialize_Transaction(d, transaction_index, owner_keys)
  result = "block: "+(d['hashBlock'][::-1]).encode('hex_codec')
  result += " %d hashes in merkle branch\n"%(len(d['merkleBranch'])/32,)
  return result+tx

def parse_WalletTx(vds):
  d = parse_MerkleTx(vds)
  n_vtxPrev = vds.read_compact_size()
  d['vtxPrev'] = []
  for i in range(n_vtxPrev):
    d['vtxPrev'].append(parse_MerkleTx(vds))

  d['mapValue'] = {}
  n_mapValue = vds.read_compact_size()
  for i in range(n_mapValue):
    key = vds.read_string()
    value = vds.read_string()
    d['mapValue'][key] = value
  n_orderForm = vds.read_compact_size()
  d['orderForm'] = []
  for i in range(n_orderForm):
    first = vds.read_string()
    second = vds.read_string()
    d['orderForm'].append( (first, second) )
  d['fTimeReceivedIsTxTime'] = vds.read_uint32()
  d['timeReceived'] = vds.read_uint32()
  d['fromMe'] = vds.read_boolean()
  d['spent'] = vds.read_boolean()

  return d

def deserialize_WalletTx(d, transaction_index=None, owner_keys=None):
  result = deserialize_MerkleTx(d, transaction_index, owner_keys)
  result += "%d vtxPrev txns\n"%(len(d['vtxPrev']),)
  result += "mapValue:"+str(d['mapValue'])
  if len(d['orderForm']) > 0:
    result += "\n"+" orderForm:"+str(d['orderForm'])
  result += "\n"+"timeReceived:"+time.ctime(d['timeReceived'])
  result += " fromMe:"+str(d['fromMe'])+" spent:"+str(d['spent'])
  return result

# The CAuxPow (auxiliary proof of work) structure supports merged mining.
# A flag in the block version field indicates the structure's presence.
# As of 8/2011, the Original Bitcoin Client does not use it.  CAuxPow
# originated in Namecoin; see
# https://github.com/vinced/namecoin/blob/mergedmine/doc/README_merged-mining.md.
def parse_AuxPow(vds):
  d = parse_MerkleTx(vds)
  n_chainMerkleBranch = vds.read_compact_size()
  d['chainMerkleBranch'] = vds.read_bytes(32*n_chainMerkleBranch)
  d['chainIndex'] = vds.read_int32()
  d['parentBlock'] = parse_BlockHeader(vds)
  return d

def parse_BlockHeader(vds):
  d = {}
  header_start = vds.read_cursor
  d['version'] = vds.read_int32()
  d['hashPrev'] = vds.read_bytes(32)
  d['hashMerkleRoot'] = vds.read_bytes(32)
  d['nTime'] = vds.read_uint32()
  d['nBits'] = vds.read_uint32()
  d['nNonce'] = vds.read_uint32()
  header_end = vds.read_cursor
  d['__header__'] = vds.input[header_start:header_end]
  return d

def parse_Block(vds):
  d = parse_BlockHeader(vds)
  d['transactions'] = []
#  if d['version'] & (1 << 8):
#    d['auxpow'] = parse_AuxPow(vds)
  nTransactions = vds.read_compact_size()
  for i in range(nTransactions):
    d['transactions'].append(parse_Transaction(vds))

  return d
  
def deserialize_Block(d, print_raw_tx=False, version=b'\x00'):
  result = []
  # block timestamps are unreliable 
  # make sure it is less than current time
  current_time = int(time.time())
  block_time =  d['nTime'] if  d['nTime'] < current_time else current_time
  for t in d['transactions']:
    tx = deserialize_Transaction(t, print_raw_tx=print_raw_tx, version=version)
    tx['time'] = block_time
    result.append(tx)
  return result

def parse_BlockLocator(vds):
  d = { 'hashes' : [] }
  nHashes = vds.read_compact_size()
  for i in range(nHashes):
    d['hashes'].append(vds.read_bytes(32))
  return d

def deserialize_BlockLocator(d):
  result = "Block Locator top: "+d['hashes'][0][::-1].encode('hex_codec')
  return result

opcodes = Enumeration("Opcodes", [
    ("OP_0", 0), ("OP_PUSHDATA1",76), "OP_PUSHDATA2", "OP_PUSHDATA4", "OP_1NEGATE", "OP_RESERVED",
    "OP_1", "OP_2", "OP_3", "OP_4", "OP_5", "OP_6", "OP_7",
    "OP_8", "OP_9", "OP_10", "OP_11", "OP_12", "OP_13", "OP_14", "OP_15", "OP_16",
    "OP_NOP", "OP_VER", "OP_IF", "OP_NOTIF", "OP_VERIF", "OP_VERNOTIF", "OP_ELSE", "OP_ENDIF", "OP_VERIFY",
    "OP_RETURN", "OP_TOALTSTACK", "OP_FROMALTSTACK", "OP_2DROP", "OP_2DUP", "OP_3DUP", "OP_2OVER", "OP_2ROT", "OP_2SWAP",
    "OP_IFDUP", "OP_DEPTH", "OP_DROP", "OP_DUP", "OP_NIP", "OP_OVER", "OP_PICK", "OP_ROLL", "OP_ROT",
    "OP_SWAP", "OP_TUCK", "OP_CAT", "OP_SUBSTR", "OP_LEFT", "OP_RIGHT", "OP_SIZE", "OP_INVERT", "OP_AND",
    "OP_OR", "OP_XOR", "OP_EQUAL", "OP_EQUALVERIFY", "OP_RESERVED1", "OP_RESERVED2", "OP_1ADD", "OP_1SUB", "OP_2MUL",
    "OP_2DIV", "OP_NEGATE", "OP_ABS", "OP_NOT", "OP_0NOTEQUAL", "OP_ADD", "OP_SUB", "OP_MUL", "OP_DIV",
    "OP_MOD", "OP_LSHIFT", "OP_RSHIFT", "OP_BOOLAND", "OP_BOOLOR",
    "OP_NUMEQUAL", "OP_NUMEQUALVERIFY", "OP_NUMNOTEQUAL", "OP_LESSTHAN",
    "OP_GREATERTHAN", "OP_LESSTHANOREQUAL", "OP_GREATERTHANOREQUAL", "OP_MIN", "OP_MAX",
    "OP_WITHIN", "OP_RIPEMD160", "OP_SHA1", "OP_SHA256", "OP_HASH160",
    "OP_HASH256", "OP_CODESEPARATOR", "OP_CHECKSIG", "OP_CHECKSIGVERIFY", "OP_CHECKMULTISIG",
    "OP_CHECKMULTISIGVERIFY",
    "OP_NOP1", "OP_NOP2", "OP_NOP3", "OP_NOP4", "OP_NOP5", "OP_NOP6", "OP_NOP7", "OP_NOP8", "OP_NOP9", "OP_NOP10",
    ("OP_INVALIDOPCODE", 0xFF),
])

def script_GetOp(bytes):
  i = 0
  while i < len(bytes):
    vch = None
    opcode = bytes[i]
    i += 1

    if opcode <= opcodes.OP_PUSHDATA4:
      nSize = opcode
      if opcode == opcodes.OP_PUSHDATA1:
        nSize = bytes[i]
        i += 1
      elif opcode == opcodes.OP_PUSHDATA2:
        (nSize,) = struct.unpack_from('<H', bytes, i)
        i += 2
      elif opcode == opcodes.OP_PUSHDATA4:
        (nSize,) = struct.unpack_from('<I', bytes, i)
        i += 4
      if i+nSize > len(bytes):
        vch = b"_INVALID_"+bytes[i:]
        i = len(bytes)
      else:
        vch = bytes[i:i+nSize]
        i += nSize

    yield (opcode, vch)

def script_GetOpName(opcode):
  try:
    return (opcodes.whatis(opcode)).replace("OP_", "")
  except KeyError:
    return "InvalidOp_"+str(opcode)

def decode_script(bytes):
  result = ''
  for (opcode, vch) in script_GetOp(bytes):
    if len(result) > 0: result += " "
    if opcode <= opcodes.OP_PUSHDATA4:
      result += "%d:"%(opcode,)
      result += short_hex(vch)
    else:
      result += script_GetOpName(opcode)
  return result

def match_decoded(decoded, to_match):
  if len(decoded) != len(to_match):
    return False;
  for i in range(len(decoded)):
    if to_match[i] == opcodes.OP_PUSHDATA4 and decoded[i][0] <= opcodes.OP_PUSHDATA4:
      continue  # Opcodes below OP_PUSHDATA4 all just push data onto stack, and are equivalent.
    if to_match[i] != decoded[i][0]:
      return False
  return True

def extract_public_key(bytes, version=b'\x00'):
  try:
    decoded = [ x for x in script_GetOp(bytes) ]
  except (struct.error, IndexError):
    return None
  # non-generated TxIn transactions push a signature
  # (seventy-something bytes) and then their public key
  # (33 or 65 bytes) onto the stack:
  match = [ opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4 ]
  if match_decoded(decoded, match):
    if (decoded[0][0]==0 and decoded[1][0] in [20, 32]):
      #Native Segwit P2PKH or P2SH output
      #bech32 addresses always have version 0
      ff = [x for x in decoded[1][1]]
      return segwit_addr.encode(segwit_addr.SEGWIT_HRPS[version.decode()], 0, ff)
    return public_key_to_bc_address(decoded[1][1], version=version)

  # bech32m has version byte 1, OP_1
  # and then witness program 20 or 32 bytes
  match = [ opcodes.OP_1, opcodes.OP_PUSHDATA4 ]
  if match_decoded(decoded, match):
    if (decoded[1][0] in [20, 32]):
      ff = [x for x in decoded[1][1]]
      return segwit_addr.encode(segwit_addr.SEGWIT_HRPS[version.decode()], 1, ff)

  # The Genesis Block, self-payments, and pay-by-IP-address payments look like:
  # 65 BYTES:... CHECKSIG
  match = [ opcodes.OP_PUSHDATA4, opcodes.OP_CHECKSIG ]
  if match_decoded(decoded, match):
    return public_key_to_bc_address(decoded[0][1], version=version)

  # Pay-by-Bitcoin-address TxOuts look like:
  # DUP HASH160 20 BYTES:... EQUALVERIFY CHECKSIG
  match = [ opcodes.OP_DUP, opcodes.OP_HASH160, opcodes.OP_PUSHDATA4, opcodes.OP_EQUALVERIFY, opcodes.OP_CHECKSIG ]
  if match_decoded(decoded, match) and len(decoded[2][1])==20:
    return hash_160_to_bc_address(decoded[2][1], version=version)

  # BIP11 TxOuts look like one of these:
  # Note that match_decoded is dumb, so OP_1 actually matches OP_1/2/3/etc:
  multisigs = [
    [ opcodes.OP_1, opcodes.OP_PUSHDATA4, opcodes.OP_1, opcodes.OP_CHECKMULTISIG ],
    [ opcodes.OP_2, opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4, opcodes.OP_2, opcodes.OP_CHECKMULTISIG ],
    [ opcodes.OP_3, opcodes.OP_PUSHDATA4, opcodes.OP_PUSHDATA4, opcodes.OP_3, opcodes.OP_CHECKMULTISIG ]
  ]
  for match in multisigs:
    if match_decoded(decoded, match):
      return [public_key_to_bc_address(decoded[i][1], version=version) for i in range(1,len(decoded)-1)]

  # BIP16 TxOuts look like:
  # HASH160 20 BYTES:... EQUAL
  match = [ opcodes.OP_HASH160, 0x14, opcodes.OP_EQUAL ]
  if match_decoded(decoded, match):
    script_version = b'\x05' if version==b'\x00' else b'\xC4'
    return hash_160_to_bc_address(decoded[1][1], version=script_version)

  return None
