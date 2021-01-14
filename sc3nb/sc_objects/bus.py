#Control Bus Commands


#/c_set
#Set bus value(s).

#N *	
#int	a bus index
#float or int	a control value
#Takes a list of pairs of bus indices and values and sets the buses to those values.

#/c_setn
#Set ranges of bus value(s).

#N *	
#int	starting bus index
#int	number of sequential buses to change (M)
#M *	
#float or int	a control value
#Set contiguous ranges of buses to sets of values. For each range, the starting bus index is given followed by the number of channels to change, followed by the values.

#/c_fill
#Fill ranges of bus value(s).

#N *	
#int	starting bus index
#int	number of buses to fill (M)
#float or int	value
#Set contiguous ranges of buses to single values. For each range, the starting sample index is given followed by the number of buses to change, followed by the value to fill.

#/c_get
#Get bus value(s).

#N * int	a bus index
#Takes a list of buses and replies to sender with the corresponding /c_set command.

#/c_getn
#Get ranges of bus value(s).

#N *	
#int	starting bus index
#int	number of sequential buses to get (M)
#Get contiguous ranges of buses. Replies to sender with the corresponding /c_setn command.