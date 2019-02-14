import pandas as pd
import numpy as np
import statsmodels.stats.multitest
from get_indra_stmts import load_genes
from nx_mg_assembler import Nx_MG_Assembler

class GeneWalk(object):
    """GeneWalk object that generates the final output list of significant GO terms
    for each gene in the input list with genes of interest from an experiment, eg DE genes or CRISPR screen hits. 
    If an input gene is not in the output, this could have several reasons: 
    1) there are no GO annotations or INDRA statements for this gene or 
    2) no annotated GO terms were significant at the chosen significance level (alpha_FDR).

    Parameters
    ----------
    folder : folder where files are located and generated (default '~/'),
    fhgnc : filename of input list with HGNC ids from genes of interest, (default: 'HGNCidForINDRA.csv'), 
    fstmts : pickle file with INDRA statements as generated with get_indra_stmts.py (default: 'HGNCidForINDRA.pkl'),
    fmg : pickle file with networkx multigraph as generated with nx_mg_assembler.py (default: 'GeneWalk_MG.pkl'),
    fnv : pickle file with node vectors as generated with deepwalk.py (default: 'GeneWalk_DW_nv.pkl'),
    fnull_dist : pickle file with null distributions for significance testing as generated
                with get_null_distributions.py (default: 'GeneWalk_DW_rand_simdists.pkl') 
    
    Attributes
    ----------
    hgncid : list of HGNC ids from genes of interest (loaded from fhgnc)
    MG : Nx_MG_Assembler object, with indra statements as MG.stmts (loaded from fstmts) and MG.graph (loaded from fmg)
    nv : node vectors (loaded from fnv) 
    srd : similarity random (null) distributions (loaded from fnull_dist)
    outdf : pandas.DataFrame that will be the final result of GeneWalk
    """
    
    def __init__(self,folder='~/',
                 fhgnc='HGNCidForINDRA.csv',
                 fstmts='HGNCidForINDRA.pkl',
                 fmg='GeneWalk_MG.pkl',
                 fnv='GeneWalk_DW_nv.pkl',
                 fnull_dist='GeneWalk_DW_rand_simdists.pkl'):
        self.path=folder
        self.hgncid=load_genes(path+fhgnc)#read hgnc list of interest
        self.outdf=pd.DataFrame(columns=['HGNC:ID','HUGO','GO description','GO:ID',
                                                'N_con(gene)','N_con(GO)',
                                                'similarity','pval','padj'])
        # Open pickled statements and initialize Nx_MG_Assembler
        with open(path+fstmts, 'rb') as f:
            stmts=pkl.load(f)
        self.MG=Nx_MG_Assembler(stmts,'/n/groups/churchman/ri23/GO/')
        del(stmts)    
        #load multigraph
        with open(path+fmg, 'rb') as f:
            self.MG.graph=pkl.load(f)
        self.GO_nodes=set(nx.get_node_attributes(self.MG.graph,'GO'))
        # load all node vectors    
        with open(path+fnv, 'rb') as f:
            self.nv=pkl.load(f)
        # Load similarity null distributions for significance testing       
        with open(path+fnull_dist, 'rb') as f:
            self.srd = pkl.load(f)
        
    
    def generate_output(self,alpha_FDR=0.05,fname_out='GeneWalk.csv'): 
        """main function of GeneWalk object that generates the final output list 

        Parameters
        ----------
        alpha_FDR :  significance level for FDR (default=0.05)
        fname_out : filename of GeneWalk output file (default=GeneWalk.csv)
        """
        g_view=nx.nodes(self.MG.graph)
        for n in g_view:
            try: 
                if self.MG.graph.node[n]['HGNC'] in self.hgncid:
                    N_gene_con=len(self.MG.graph[n])
                    GOdf=self.get_GO_df(n,N_gene_con,alpha_FDR)
                    GOdf.insert(loc=0,column='HGNC:ID', value=pd.Series(GW[tr].MG.graph.node[n]['HGNC'], index=GOdf.index))
                    GOdf.insert(loc=1,column='HUGO', value=pd.Series(n, index=GOdf.index))
                    GOdf.insert(loc=4,column='N_con(gene)', value=pd.Series(N_gene_con, index=GOdf.index))
                    self.outdf=self.outdf.append(GOdf, ignore_index=True)
            except KeyError:
                pass
        self.outdf['HGNC:ID'] = self.outdf['HGNC:ID'].astype("category")
        self.outdf['HGNC:ID'].cat.set_categories(self.hgncid, inplace=True)#sort according to input hgncid list
        self.outdf=self.outdf.sort_values(by=['HGNC:ID','padj','pval'])
        self.outdf.to_csv(self.path+fname_out, index=False)
        return self.outdf
    
    def P_sim(self,sim,N_con):
        dist_key='d'+str(np.floor(np.log2(N_con)))
        RANK = np.searchsorted(self.srd[dist_key], sim, side='left', sorter=None)
        PCT_RANK = float(RANK)/len(self.srd[dist_key])
        pval=1-PCT_RANK
        return pval

    def get_GO_df(self,geneoi,N_gene_con,alpha_FDR):
        N_GO_CON=[]
        PVAL=[]
        FDR=[]
        DES=[]
        GO_con2gene=set(self.MG.graph[geneoi]).intersection(self.GO_nodes)
        simdf=pd.DataFrame(self.nv.most_similar(geneoi,topn=len(self.nv.vocab)),columns=['GO:ID','similarity'])
        simdf=simdf[simdf['GO:ID'].isin(GO_con2gene)]
        
        for i in simdf.index:
            N_GO_con=len(self.MG.graph[simdf['GO:ID'][i]])
            N_GO_CON.append(N_GO_con)
            DES.append(self.MG.graph.node[simdf['GO:ID'][i]]['name'])
            pval=self.P_sim(simdf['similarity'][i],min(N_GO_con,N_gene_con))
            PVAL.append(pval)
        simdf.insert(loc=0,column='GO description', value=pd.Series(DES, index=simdf.index))
        simdf.insert(loc=2,column='N_con(GO)', value=pd.Series(N_GO_CON, index=simdf.index))
        simdf.insert(loc=4,column='pval', value=pd.Series(PVAL, index=simdf.index))
        BOOL,q_val=statsmodels.stats.multitest.fdrcorrection(simdf['pval'], 
                                                     alpha=alpha_FDR, method='indep')
        simdf.insert(loc=5,column='padj', value=pd.Series(q_val, index=simdf.index))
        return simdf[simdf['padj']<alpha_FDR]
