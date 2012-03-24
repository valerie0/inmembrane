import os
import helpers
from helpers import dict_get, eval_surface_exposed_loop, \
                    chop_nterminal_peptide, log_stderr

def predict_surface_exposure_barrel(params, protein):
  # TODO: This is a placeholder for a function which will do something
  #       similar to predict_surface_exposure, but focussed on inferring 
  #       outer membrane beta barrel topology.
  #       Essentially, we should:
  #        * Move through the strand list in reverse.
  #        * Strand annotation alternates 'up' strand and 'down' strand
  #        * Loop annotation (starting with the C-terminal residue) alternates
  #          'inside' and 'outside'.
  #        * If everything is sane, we should finish on a down strand. If not,
  #          consider a rule to make an 'N-terminal up strand' become 
  #          an 'inside loop'
  #        * Sanity check on loop lengths ? 'Outside' loops should be on average
  #          longer than non-terminal 'inside' loops.
  #        * For alternative strand predictors (eg transFold, ProfTMB), which
  #          may specifically label inner and outer loops, we should obviously
  #          use those annotations directly.
  pass


def print_summary_table(params, proteins):
  counts = {}
  counts["BARREL"] = 0
  for seqid in proteins:
    category = proteins[seqid]['category']
    
    # WIP: greedy barrel annotation
    if (dict_get(proteins[seqid], 'tmbhunt_prob') >= params['tmbhunt_cutoff']) or \
       (dict_get(proteins[seqid], 'bomp') >= params['bomp_cutoff']):
       counts["BARREL"] += 1
    
    if category not in counts:
      counts[category] = 0
    else:
      counts[category] += 1
      
  log_stderr("# Number of proteins in each class:")
  for c in counts:
    log_stderr("%-15s %i" % (c, counts[c]))

# TODO: Workflow:
#       These rules can be approached in two ways. Run every annotation plugin
#       on every sequence, then post-hoc apply these rules (potentially inefficient
#       and rude to web services). Alternatively the protocol can control the
#       annotation loop and only run certain analyses (eg BOMP) if a certain 
#       condition is met (eg is_signalp). 
#       * If is_lipop, 
#         check retention signal annotation (+2Asp) -> periplasmic inner or outer
#       * If is_signalp (or TAT) and no other TM and not is_lipop -> periplasmic
#       * If is_signalp, run OMPBB (BOMP) check. If OMPBB -> outer membrane bb
#       * If is_signalp, and has after the signal tranmembranes -> inner membrane
#       * If inner membrane, check for long cyto or peri loops: inner[+cyto][+peri]
#       * If not is_signalp and not is_lipop (and not TAT): -> cytoplasmic
def get_annotations(params):
  annotations = ['annotate_signalp4', 'annotate_lipop1']
  #annotations += ['annotate_tatp']
  annotations += ['annotate_bomp']
  
  # TMBETA-NET knows to only run on predicted barrels
  # with the category 'OM(barrel)'
  if 'tmbeta' in dict_get(params, 'barrel_programs'):
    annotations.append('annotate_tmbeta_net_web')

  if dict_get(params, 'helix_programs'):
    if 'tmhmm' in params['helix_programs']:
      annotations.append('annotate_tmhmm')
    if 'memsat3' in params['helix_programs']:
      annotations.append('annotate_memsat3')

  # currently we don't use any HMM profiles on gram-
  # annotation, but this may be useful in the future
  #annotations += ['annotate_hmmsearch3']
  #params['hmm_profiles_dir'] = os.path.join(
  #    os.path.dirname(__file__), 'gram_neg_profiles')

  return annotations

def post_process_protein(params, protein, stringent=False):
    
  def has_tm_helix(protein):
    for program in params['helix_programs']:
      if dict_get(protein, '%s_helices' % program):
        return True
    return False

  # TODO: rather than this, lets classify each inner membrane protein as 
  # IM with optional large periplasmic or large cytoplasmic loops/domain
  # (eg possible classifications: IM+cyt, IM+peri, IM+cyt+peri )
  def has_periplasmic_loop(protein):
    for program in params['helix_programs']:
      if eval_surface_exposed_loop(
          protein['sequence_length'], 
          len(protein['%s_helices' % (program)]), 
          protein['%s_outer_loops' % (program)], 
          params['terminal_exposed_loop_min'], 
          params['internal_exposed_loop_min']):
        return True
    return False
  
  details = []
  #is_hmm_profile_match = dict_get(protein, 'hmmsearch')
  is_signalp = dict_get(protein, 'is_signalp')
  # TODO: in terms of logic, a Tat signal is essentially the same
  #       as a Sec (signalp) signal. Consider setting is_signalp = True
  #       if is_tatp = True, so all logic just looks at is_signalp
  #is_tatp = dict_get(protein, 'is_tatp')
  is_lipop = dict_get(protein, 'is_lipop')
  
  is_barrel = False
  if dict_get(protein, 'bomp'):
    is_barrel = True
    details += ['bomp']
  if dict_get(protein, 'tmbhunt'):
    is_barrel = True 
    details += ['tmbhunt']
  
  # if stringent, predicted OM barrels must also have a predicted
  # signal sequence 
  if stringent and is_signalp and is_barrel:
     protein['category'] = 'OM(barrel)'
  elif is_barrel:
     protein['category'] = 'OM(barrel)'
  
  # set number of predicted OM barrel strands in details
  if dict_get(protein, 'tmbeta_strands'):
    num_strands = len(protein['tmbeta_strands'])
    details += ['tmbeta_strands(%i)' % (num_strands)]
  
  #if is_tatp:
  #  details += ["tatp"]
  #  if not is_lipop:
  #    chop_nterminal_peptide(protein,  protein['tatp_cleave_position'])
  
  if is_signalp:
    details += ["signalp"]
    if not is_lipop:
      chop_nterminal_peptide(protein,  protein['signalp_cleave_position'])
  
  if is_lipop:
    details += ["lipop"]
    chop_nterminal_peptide(protein, protein['lipop_cleave_position'])
  
  #if is_hmm_profile_match:
  #  details += ["hmm(%s)" % protein['hmmsearch'][0]]

  if has_tm_helix(protein) and not is_barrel:
    for program in params['helix_programs']:
      n = len(protein['%s_helices' % program])
      details += [program + "(%d);" % n]
    
    # TODO: detect long periplasmic OR cytoplasmic loops 
    if has_periplasmic_loop(protein):
      category = "IM+peri"
    else:
      category = "IM"
  elif not is_barrel:
    if is_lipop:
      # TODO: check for inner vs. outer lipoprotein annotation
      #       classify as LIPOPROTEIN(IM) or LIPOPROTEIN(OM)
      category = "LIPOPROTEIN"
      pass
    elif is_signalp:
      category = "SECRETED"
    else:
      category = "CYTOPLASM"

  if details is []:
    details = ["."]

  protein['details'] = details
  protein['category'] = category

  return details, category


def protein_output_line(seqid, proteins):
  return '%-15s   %-13s  %-50s  %s' % \
      (seqid, 
      proteins[seqid]['category'], 
      ";".join(proteins[seqid]['details']),
      proteins[seqid]['name'][:60])

def protein_csv_line(seqid, proteins):
  return '%s,%s,%s,"%s"\n' % \
      (seqid, 
       proteins[seqid]['category'], 
       ";".join(proteins[seqid]['details']),
       proteins[seqid]['name'])
